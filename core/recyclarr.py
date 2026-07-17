# core/recyclarr.py
"""
Syncs TRaSH Guides-recommended quality profiles / custom formats / quality
definitions into Sonarr and Radarr via the `recyclarr/recyclarr` Docker
image, run one-shot (not recyclarr's own built-in cron) so it fits the same
watchdog-thread scheduling this app already uses for vuln/integrity scans.

Mechanics, verified against a live server rather than assumed:
  - `recyclarr config create --template <id>` materializes a full starter
    config for that template under /config/configs/<id>.yml inside the
    container. (The older `include: - template:` directive against the
    official config-templates repo no longer works as of v8 -- that's a
    different, deprecated mechanism.) The app-data directory only
    auto-detects as /config under recyclarr's documented compose setup, not
    a plain `docker run image ...` invocation, so RECYCLARR_CONFIG_DIR/
    RECYCLARR_DATA_DIR are passed explicitly on every invocation.
  - Generated template files ship with base_url/api_key already set to
    instructional placeholder text ("Put your Sonarr URL here"), not
    omitted -- so recyclarr's documented "implicit secrets" convention
    (which only fires when the field is *absent*) never actually applies to
    a freshly generated template. Real credentials are written directly
    into the parsed structure instead.
  - Each template names its own instance after itself (e.g. "web-1080p").
    Syncing multiple templates against the same real server in one
    `recyclarr sync -c file1 -c file2 ...` call was tried both ways and
    both fail: different instance names sharing a base_url get rejected as
    ambiguous "Split Instances", and giving them the same name gets
    rejected as "duplicate instances". Recyclarr expects one YAML document
    per real server, not several files referencing it -- so every selected
    template for a service is parsed and merged into a single instance
    definition (quality_profiles/custom_formats lists concatenated) before
    being handed to `recyclarr sync`.

This module is read/write against the *recyclarr* config on the server, and
read-only against Sonarr/Radarr's own config in this app -- it never
modifies core/config_manager's Sonarr/Radarr settings.
"""

import os
import shlex
import tempfile

import yaml

_IMAGE = "recyclarr/recyclarr"

# Every path below has to survive being re-quoted at least twice (once by
# shlex.quote() here, once more inside ssh.put_file()'s own single-quoted
# `sudo tee '<path>'`), and single quotes suppress shell variable expansion
# -- so a literal "$HOME" placeholder silently resolves to nothing instead
# of the real home dir once it's inside a second layer of quoting. Resolve
# the real path once per connection instead of ever embedding "$HOME" in a
# path that gets quoted downstream.
_home_cache = {}


def _home_dir(ssh) -> str:
    key = id(ssh)
    if key not in _home_cache:
        out, _err, code = ssh.run("printf '%s' \"$HOME\"")
        _home_cache[key] = out.strip() if code == 0 and out.strip() else "/root"
    return _home_cache[key]


def _config_dir(ssh) -> str:
    return "{}/docker/recyclarr/config".format(_home_dir(ssh))


# Curated subset of the *live* template registry -- confirmed against a
# real `recyclarr config list templates` run (v8.3.2) rather than GitHub's
# templates.json, which turned out to use stale names (e.g. "web-1080p-v4"
# instead of the registry's actual "web-1080p": recyclarr's own
# `config create --template <id>` silently no-ops on an unrecognized id
# instead of erroring, which is what made this so hard to track down).
# Not the full catalog (French/German language-specific and the SQP tiers
# are left out to keep the picker short; add here if requested).
TEMPLATES = {
    "radarr": [
        ("hd-bluray-web",            "HD Bluray + WEB (1080p)"),
        ("uhd-bluray-web",           "UHD Bluray + WEB (2160p)"),
        ("remux-web-1080p",          "Remux + WEB (1080p)"),
        ("remux-web-2160p",          "Remux + WEB (2160p)"),
        ("radarr-anime-remux-1080p", "Anime"),
    ],
    "sonarr": [
        ("web-1080p",                "WEB (1080p)"),
        ("web-2160p",                "WEB (2160p)"),
        ("sonarr-anime-remux-1080p", "Anime"),
    ],
}

_TEMPLATE_SERVICE = {tid: svc for svc, entries in TEMPLATES.items() for tid, _ in entries}

_ENV_FLAGS = "-e RECYCLARR_CONFIG_DIR=/config -e RECYCLARR_DATA_DIR=/config"


def _docker_run(ssh, extra_args: str) -> str:
    return "docker run --rm -v {}:/config {} {} {}".format(
        _config_dir(ssh), _ENV_FLAGS, _IMAGE, extra_args)


def ensure_config_dir(ssh):
    ssh.run("mkdir -p {}/configs".format(_config_dir(ssh)))


def generate_template_config(ssh, template_id: str) -> tuple:
    """
    Runs `recyclarr config create --template <id>` inside the container.
    Returns (remote_path, error) -- remote_path is None on failure.

    Overrides the entrypoint with a shell so recyclarr's own stdout/stderr
    and the configs directory / newest log tail can all be captured
    *inside* the container before --rm tears it down -- if the expected
    output file doesn't show up, the returned error carries that context
    instead of a bare "failed" with no way to tell why.
    """
    ensure_config_dir(ssh)
    config_dir = _config_dir(ssh)
    dest = "{}/configs/{}.yml".format(config_dir, template_id)

    inner = (
        "recyclarr config create --template {tid} --force 2>&1; "
        "echo RECYCLARR_EXIT:$?; "
        "echo ---CONFIGS-DIR---; "
        "ls -la /config/configs; "
        "echo ---NEWEST-LOG---; "
        "f=$(ls -t /config/logs/cli/*.verbose.log 2>/dev/null | head -1); "
        "[ -z \"$f\" ] && f=$(ls -t /config/logs/cli/*.log 2>/dev/null | head -1); "
        "tail -c 4000 \"$f\" 2>/dev/null"
    ).format(tid=shlex.quote(template_id))
    cmd = "docker run --rm --entrypoint /bin/sh -v {}:/config {} {} -c {}".format(
        config_dir, _ENV_FLAGS, _IMAGE, shlex.quote(inner))
    out, err, _code = ssh.run(cmd)
    # Both streams matter here: recyclarr's own error text (if any) can land
    # on either one, and `out or err` would silently drop err's content
    # whenever the echoed markers above already made out non-empty.
    diagnostic = "\n".join(s for s in (out, err) if s and s.strip()).strip()

    check_out, _e, check_code = ssh.run("test -f {} && echo found".format(shlex.quote(dest)))
    if check_code == 0 and "found" in (check_out or ""):
        return dest, None

    return None, "template {} never landed at {}; container diagnostic:\n{}".format(
        template_id, dest, diagnostic[:1500])


def read_remote_file(ssh, remote_path: str) -> tuple:
    """Returns (content, error)."""
    out, err, code = ssh.run("cat {}".format(shlex.quote(remote_path)))
    if code != 0 or not out:
        return None, "could not read {} back: {}".format(
            remote_path, (err or out or "empty file").strip()[:300])
    return out, None


def write_remote_file(ssh, remote_path: str, content: str) -> tuple:
    """Returns (ok, error)."""
    fd, tmp_path = tempfile.mkstemp(suffix=".yml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        out, err, code = ssh.put_file(tmp_path, remote_path)
        if code != 0:
            return False, (err or out or "write failed").strip()[:300]
        return True, None
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def build_merged_config(ssh, service: str, template_ids: list, cfg: dict) -> tuple:
    """
    Generates every given template (all for the same service), parses each,
    and merges them into ONE instance definition: quality_profiles and
    custom_formats lists are concatenated across templates, other keys keep
    whichever template set them first, and base_url/api_key are set to the
    real Sonarr/Radarr credentials directly on the parsed structure.

    Returns (remote_path, error) -- remote_path points at the single merged
    file written for this service.
    """
    merged = {}
    for tid in template_ids:
        remote_path, gen_err = generate_template_config(ssh, tid)
        if gen_err:
            return None, "{}: {}".format(tid, gen_err)

        content, read_err = read_remote_file(ssh, remote_path)
        if read_err:
            return None, "{}: {}".format(tid, read_err)

        try:
            doc = yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            return None, "{}: could not parse generated YAML: {}".format(tid, e)

        instances = doc.get(service) or {}
        if not instances:
            return None, "{}: no {}: instance found in generated file; raw content:\n{}".format(
                tid, service, content[:1000])
        instance_doc = next(iter(instances.values())) or {}

        for key, value in instance_doc.items():
            if key in ("quality_profiles", "custom_formats") and isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            elif key not in merged:
                merged[key] = value

    host = str(cfg.get("host", "localhost")).removeprefix("https://").removeprefix("http://").strip("/")
    merged["base_url"] = "http://{}:{}".format(host, cfg.get("port", ""))
    merged["api_key"] = cfg["apikey"]

    yaml_text = yaml.safe_dump({service: {service: merged}}, default_flow_style=False, sort_keys=False)
    remote_path = "{}/configs/merged-{}.yml".format(_config_dir(ssh), service)
    ok, write_err = write_remote_file(ssh, remote_path, yaml_text)
    if not ok:
        return None, "failed to write merged {} config: {}".format(service, write_err)
    return remote_path, None


def run_sync(ssh, services: list) -> dict:
    """
    Runs `recyclarr sync -c <file> -c <file> ...` across the given
    already-merged config file(s), one per service.

    Takes service names, not the host-side paths build_merged_config()
    returns: -c needs a path as seen *inside* the container (mounted at
    /config), not the host path used for ssh.put_file()/cat -- passing the
    host path here was tried and confirmed broken against a live server
    ("config files not found"), since that path means nothing inside the
    container's own filesystem.

    Returns {"ok", "raw", "error"} -- raw is recyclarr's own table output
    (kept verbatim for the console widget rather than parsed, since it's a
    Spectre.Console table with color/box-drawing chars that isn't a stable
    thing to regex-parse field-by-field).
    """
    if not services:
        return {"ok": False, "raw": "", "error": "No templates selected."}
    config_flags = " ".join(
        "-c /config/configs/merged-{}.yml".format(shlex.quote(s)) for s in services)
    cmd = _docker_run(ssh, "sync {} 2>&1".format(config_flags))
    out, err, code = ssh.run(cmd)
    text = (out or err or "").strip()
    # Piped through a non-TTY, Spectre.Console's live progress display
    # re-prints a full frame per tick instead of updating in place -- for a
    # multi-instance sync that can run to tens of KB, almost all of it
    # redundant intermediate frames. The *final* frame (with every
    # instance's real ✓/counts) is what's actually useful, so keep the tail
    # rather than the head.
    return {"ok": code == 0, "raw": text[-8000:],
            "error": None if code == 0 else text[-300:]}


def sync_templates(ssh, template_ids: list, sonarr_cfg: dict, radarr_cfg: dict) -> dict:
    """
    Full pipeline: group selected templates by service, merge each
    service's templates into one instance definition with real credentials,
    then sync. Returns {"ok", "raw", "error"}.
    """
    if not template_ids:
        return {"ok": False, "raw": "", "error": "No templates selected."}

    by_service = {}
    for tid in template_ids:
        svc = _TEMPLATE_SERVICE.get(tid)
        if not svc:
            return {"ok": False, "raw": "", "error": "Unknown template: {}".format(tid)}
        by_service.setdefault(svc, []).append(tid)

    cfg_by_service = {"sonarr": sonarr_cfg, "radarr": radarr_cfg}
    services = []
    for service, tids in by_service.items():
        cfg = cfg_by_service.get(service) or {}
        if not cfg.get("apikey"):
            return {"ok": False, "raw": "",
                    "error": "No {} API key configured (needed for: {}).".format(
                        service, ", ".join(tids))}
        _remote_path, err = build_merged_config(ssh, service, tids, cfg)
        if err:
            return {"ok": False, "raw": "", "error": err}
        services.append(service)

    return run_sync(ssh, services)
