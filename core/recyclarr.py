# core/recyclarr.py
"""
Syncs TRaSH Guides-recommended quality profiles / custom formats / quality
definitions into Sonarr and Radarr via the `recyclarr/recyclarr` Docker
image, run one-shot (not recyclarr's own built-in cron) so it fits the same
watchdog-thread scheduling this app already uses for vuln/integrity scans.

Mechanics, verified against the current (v8+) recyclarr docs rather than
assumed:
  - `recyclarr config create --template <id>` materializes a full starter
    config for that template under /config/configs/<id>.yml inside the
    container. (The older `include: - template:` directive against the
    official config-templates repo no longer works as of v8 -- that's a
    different, deprecated mechanism.)
  - Generated template files intentionally omit base_url/api_key so they
    stay shareable. Recyclarr's "implicit secrets" convention fills them in
    from a secrets.yml using <instance_name>_base_url / <instance_name>_api_key
    -- so credentials never have to be written into the template file
    itself, only into secrets.yml. The instance name is decided by the
    template, not by us, so discover_instances() reads it back rather than
    guessing.
  - `recyclarr sync` accepts multiple `-c <file>` flags to sync several
    templates in one run.

This module is read/write against the *recyclarr* config on the server, and
read-only against Sonarr/Radarr's own config in this app -- it never
modifies core/config_manager's Sonarr/Radarr settings.
"""

import os
import re
import shlex
import tempfile

_CONFIG_DIR = "$HOME/docker/recyclarr/config"
_IMAGE = "recyclarr/recyclarr"

# Curated subset of https://github.com/recyclarr/config-templates
# templates.json -- the "primary" profile per service plus the 4K variant,
# not the full catalog (anime/French/German language-specific ones are left
# out to keep the picker short; add here if requested).
TEMPLATES = {
    "radarr": [
        ("hd-bluray-web",    "HD Bluray + WEB (1080p)"),
        ("uhd-bluray-web",   "UHD Bluray + WEB (2160p)"),
        ("remux-web-1080p",  "Remux + WEB (1080p)"),
        ("remux-web-2160p",  "Remux + WEB (2160p)"),
        ("anime-radarr",     "Anime"),
    ],
    "sonarr": [
        ("web-1080p-v4",     "WEB (1080p)"),
        ("web-2160p-v4",     "WEB (2160p)"),
        ("anime-sonarr-v4",  "Anime"),
    ],
}

_INSTANCE_RE = re.compile(r'^(sonarr|radarr):\s*\n\s{2}(\S[^:\s]*):', re.MULTILINE)


def _docker_run(extra_args: str) -> str:
    return "docker run --rm -v {}:/config {} {}".format(
        _CONFIG_DIR, _IMAGE, extra_args)


def ensure_config_dir(ssh):
    ssh.run("mkdir -p {}/configs".format(_CONFIG_DIR))


def generate_template_config(ssh, template_id: str) -> tuple:
    """
    Runs `recyclarr config create --template <id>` inside the container.
    Returns (remote_path, error) -- remote_path is None on failure.
    """
    ensure_config_dir(ssh)
    remote_rel = "/config/configs/{}.yml".format(template_id)
    cmd = _docker_run("config create --template {} --path {} --force".format(
        shlex.quote(template_id), shlex.quote(remote_rel)))
    out, err, code = ssh.run(cmd)
    if code != 0:
        return None, (err or out or "config create failed").strip()[:300]
    return "{}/configs/{}.yml".format(_CONFIG_DIR, template_id), None


def discover_instances(ssh, remote_path: str) -> list:
    """
    Returns [(service, instance_name), ...] found in a generated template
    file -- e.g. [("radarr", "movies")]. A template can only be trusted to
    declare instances for the one service it's for, but the regex checks
    both since that's cheap and avoids a second assumption.
    """
    out, _err, code = ssh.run("cat {}".format(shlex.quote(remote_path)))
    if code != 0 or not out:
        return []
    return _INSTANCE_RE.findall(out)


def build_secrets_yaml(instances: list, sonarr_cfg: dict, radarr_cfg: dict) -> str:
    """
    instances: [(service, instance_name), ...] from discover_instances(),
    pooled across every template selected for this sync.
    """
    cfg_by_service = {"sonarr": sonarr_cfg, "radarr": radarr_cfg}
    lines = []
    seen = set()
    for service, name in instances:
        if (service, name) in seen:
            continue
        seen.add((service, name))
        cfg = cfg_by_service.get(service) or {}
        if not cfg.get("apikey"):
            continue
        host = str(cfg.get("host", "localhost")).removeprefix("https://").removeprefix("http://").strip("/")
        url = "http://{}:{}".format(host, cfg.get("port", ""))
        lines.append("{}_base_url: {}".format(name, url))
        lines.append("{}_api_key: {}".format(name, cfg["apikey"]))
    return "\n".join(lines) + "\n" if lines else ""


def push_secrets(ssh, yaml_text: str) -> tuple:
    """Writes secrets.yml to the server. Returns (ok, error)."""
    fd, tmp_path = tempfile.mkstemp(suffix=".yml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(yaml_text)
        out, err, code = ssh.put_file(tmp_path, "{}/secrets.yml".format(_CONFIG_DIR))
        if code != 0:
            return False, (err or out or "failed to write secrets.yml").strip()[:300]
        return True, None
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def run_sync(ssh, template_ids: list) -> dict:
    """
    Runs `recyclarr sync -c <file> -c <file> ...` across every selected
    template's generated config in one pass.

    Returns {"ok", "raw", "error"} -- raw is recyclarr's own table output
    (kept verbatim for the console widget rather than parsed, since it's a
    Spectre.Console table with color/box-drawing chars that isn't a stable
    thing to regex-parse field-by-field).
    """
    if not template_ids:
        return {"ok": False, "raw": "", "error": "No templates selected."}
    config_flags = " ".join(
        "-c /config/configs/{}.yml".format(shlex.quote(t)) for t in template_ids)
    cmd = _docker_run("sync {} 2>&1".format(config_flags))
    out, err, code = ssh.run(cmd)
    text = (out or err or "").strip()
    return {"ok": code == 0, "raw": text[:4000],
            "error": None if code == 0 else text[:300]}


def sync_templates(ssh, template_ids: list, sonarr_cfg: dict, radarr_cfg: dict) -> dict:
    """
    Full pipeline: generate each selected template's config, discover its
    instance name(s), write secrets.yml with real credentials, then sync.
    Returns {"ok", "raw", "error"}.
    """
    instances = []
    for tid in template_ids:
        remote_path, gen_err = generate_template_config(ssh, tid)
        if gen_err:
            return {"ok": False, "raw": "", "error": "{}: {}".format(tid, gen_err)}
        instances.extend(discover_instances(ssh, remote_path))

    secrets_yaml = build_secrets_yaml(instances, sonarr_cfg, radarr_cfg)
    if not secrets_yaml:
        return {"ok": False, "raw": "",
                "error": "No matching Sonarr/Radarr API key configured for the selected templates."}

    ok, push_err = push_secrets(ssh, secrets_yaml)
    if not ok:
        return {"ok": False, "raw": "", "error": push_err}

    return run_sync(ssh, template_ids)
