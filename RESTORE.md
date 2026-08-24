# Bare-metal restore

How to rebuild this server from scratch using the full-system backup written
weekly to the `fullsystem-restic` repo by `full-system-backup.sh`. For
everyday config-level recovery (an app's settings got corrupted, etc.), use
`backup.sh`'s snapshots at `/mnt/nas/wsbackup/mediaserver/<date>/` instead —
this document is for "the server itself is gone."

**Preferred path:** after installing the fresh minimal Ubuntu server (step 1
below) and connecting to it from Media Server Manager like any other server,
use the Backup tab's **"⚠ Restore from Snapshot…"** button — it runs steps
3-5 for you, with a safety check that refuses to run against a server that
isn't actually fresh, and a typed confirmation before it touches anything.
The app runs on your workstation, not on the media server, so it survives
the server being gone.

**If the workstation itself isn't available either**, `rebuild-server.sh`
(in this repo, and also copied onto the NAS at
`/mnt/nas/wsbackup/rebuild-server.sh`) does the same thing as a standalone
script — copy it to the fresh box and run `sudo bash rebuild-server.sh`.
It only needs NAS credentials and the restic repo password, typed in when
it prompts. Same safety check, same phases, no app or GUI required.

The fully manual steps below are the last-resort fallback if neither the
app nor the script is available or working.

## What's in a snapshot

The backup is a single [restic](https://restic.net/) repository at
`/mnt/nas/wsbackup/fullsystem-restic`, tagged `fullsystem`, holding one
snapshot per weekly run (the 8 most recent are kept; older ones are pruned).
Each snapshot contains:

```
/etc /home /root /opt /var /srv /boot     # see notes below
/var/lib/media-fullbackup-info/
  dpkg-selections.txt      # `dpkg --get-selections` output
  apt-manual-packages.txt  # `apt-mark showmanual` output
  lsblk.txt, blkid.txt, parted.txt   # disk/partition layout reference
  docker-images.txt        # image:tag list that was present
```

Unlike a plain tar archive, restic **encrypts everything at rest** — the
repo is unreadable without the repo password — and deduplicates across
weekly runs, so only changed data actually gets written to the NAS each
time. It contains `etc`, `home`, `root`, `opt`, `var`, `srv`, and `boot` from
the root filesystem — not `/usr` (see step 3) and not `/proc /sys /dev /run
/tmp`.

`/boot` is included in the snapshot (so it's encrypted and versioned like
everything else) but is deliberately **excluded from the automatic
restore** — see step 5. It's still recoverable individually if you ever
need something from it.

**The repo password lives outside the backup on purpose** (it can't
protect itself). It's stored in this app's own encrypted config
(`config_manager.restic_password`, set via the Backup tab's "Save & Init
Repo" button) and written to `/home/<ssh-login-user>/.restic-password` on
the server for the unattended cron run (e.g. `/home/mediasvr/.restic-password`
— under the SSH login user's home, **not** `/root`, despite root owning the
crontab entry that reads it). If you lose both the app's config and your own
record of the password, the backup is unrecoverable — treat it like any other
encryption key and keep an independent copy somewhere safe.

Media library content (movies/tv/music/photos/etc. under `/mnt/nas/*`) is
**not** part of this backup — it already lives on the NAS, not on the
server's local disk, so it's unaffected by a server failure. A restored
server just needs its `/etc/fstab` (included in the `etc` restore) to
remount those shares again.

**Cloudflare Tunnel** (`cloudflared`) config and credentials are included
automatically — `/etc/cloudflared/config.yml` (the tunnel's ingress rules)
falls under `etc`, and its credentials file (`/root/.cloudflared/<tunnel-id>.json`)
falls under `root`, both restored in step 5 below like any other config. No
separate step is needed, but do re-verify it in step 6 — a tunnel ID is tied
to the Cloudflare account, not the hardware, so it should just work once the
`cloudflared` package itself is (re)installed.

## Restore procedure

1. **Install a minimal Ubuntu server** on the new/repaired hardware. Match
   the original release if possible (`lsblk.txt` and `parted.txt` in the
   restored manifest show the original disk layout for reference, but you
   don't need to match partitioning exactly — just get a working base
   install with network access).

2. **Mount the NAS share and install restic** so you can reach the repo:
   ```
   sudo apt install cifs-utils restic
   sudo mkdir -p /mnt/nas/wsbackup
   sudo mount -t cifs //192.168.4.50/wsbackup /mnt/nas/wsbackup -o username=<user>
   ```

3. **Restore just the system manifest first** — this is enough to get the
   package list without touching anything else yet:
   ```
   export RESTIC_REPOSITORY=/mnt/nas/wsbackup/fullsystem-restic
   export RESTIC_PASSWORD=<your repo password>
   restic snapshots --tag fullsystem          # pick a snapshot ID
   sudo -E restic restore <snapshot-id> --target / \
       --include /var/lib/media-fullbackup-info
   ```

4. **Reinstall every originally-installed package** before restoring config
   files for them — this lets each package's postinst scripts set up its own
   package-manager bookkeeping cleanly, and matches the new install's own
   kernel/libc instead of relying on old copied binaries. Use
   `dpkg-selections.txt` here, **not** `apt-manual-packages.txt`: the manual
   list is only the few dozen top-level packages you explicitly installed
   (`apt-mark showmanual`) — it deliberately excludes the ~1000+
   auto-installed dependencies underneath them (libraries, `runc`, Python
   modules, etc.). Reinstalling only the manual list leaves dpkg's database
   (about to be overwritten wholesale from the old machine in step 5) saying
   hundreds of packages are installed when only a fraction actually have
   files on disk — this is exactly what happened during the 2026-08-23
   MS-01 migration: Docker, `avahi-daemon`, `certbot`, and Emby all showed
   up as "installed" in `systemctl`/`dpkg -l` while missing the actual
   shared libraries or unit files they needed, and it took hours to
   discover piecemeal instead of catching it here in one pass.
   ```
   sudo apt update
   awk '$2=="install"{print $1}' /var/lib/media-fullbackup-info/dpkg-selections.txt \
       > /tmp/all-packages.txt
   sudo xargs -a /tmp/all-packages.txt apt install --reinstall -y
   ```
   Then verify it actually landed — `dpkg -V` reports files a package owns
   that aren't really on disk. A handful of doc/man entries is normal and
   harmless; a modified/missing shared library or binary is not:
   ```
   dpkg -V | grep missing | grep -v '/usr/share/doc/\|/usr/share/man/'
   ```
   If that turns up more than a few lines, re-run the `xargs ... apt install
   --reinstall` command above — it's idempotent and safe to repeat.

5. **Restore everything else on top of the fresh install, excluding
   `/boot`.** The fresh install already has a working bootloader/kernel for
   this hardware; restoring the old machine's `/boot` over it could break
   booting on new/different hardware:
   ```
   sudo -E restic restore <snapshot-id> --target / --exclude /boot
   ```
   If you do need something from the old `/boot` (e.g. comparing GRUB
   config, recovering a specific file):
   ```
   sudo -E restic restore <snapshot-id> --target /tmp/boot-ref --include /boot
   ```

6. **Reboot**, then confirm:
   - `mount -a` remounts all the NAS shares from the restored `/etc/fstab`
     without errors.
   - `systemctl status emby-server jellyfin sonarr radarr prowlarr bazarr
     sabnzbdplus cloudflared docker avahi-daemon certbot.timer fail2ban
     nut-server` — services come up. For `cloudflared` specifically, also
     confirm each hostname in `/etc/cloudflared/config.yml` actually
     resolves — the tunnel itself coming up doesn't guarantee every
     ingress rule's local service is listening yet. `avahi-daemon` (mDNS —
     lets other devices find the server as `<hostname>.local`) is easy to
     forget precisely because nothing else depends on it to start.
   - `sudo certbot renew --dry-run` — don't stop at `certbot.timer` being
     active or `certbot certificates` listing the cert; neither actually
     exercises the renewal path. A broken certbot install (missing Python
     deps like `josepy` or the Cloudflare DNS plugin, both hit during the
     2026-08-23 migration) can leave the timer "active" while every real
     renewal attempt would fail — the dry-run is the only check that
     actually proves auto-renewal works, including the
     `/etc/letsencrypt/renewal-hooks/deploy/emby-cert.sh` hook that
     regenerates Emby's `.pfx` from the renewed cert.
   - `docker ps -a` — every container should be `Up` (containers restart
     automatically once Docker itself is healthy; compose files were
     restored under `/opt/media/*`, and images will be re-pulled
     automatically on `docker compose up` if they weren't already present
     locally, using `/var/lib/media-fullbackup-info/docker-images.txt` as a
     reference for what should exist). None should be `Restarting` or
     `Exited` — if Docker itself failed to start, check for a missing
     `runc` binary specifically (`which runc`) — it's a separate package
     from `docker.io`/`containerd` and needs reinstalling on its own if
     step 4's verification didn't already catch it.
   - **New hardware means a new MAC address**, which breaks anything on
     your router keyed to the old one — DHCP reservations and port-forwards
     alike (this is what broke Emby's external/WAN access during the
     2026-08-23 migration: the port-8920 forward was still pointed at the
     old machine). The bonded/primary interface's MAC is systemd-generated
     from `/etc/machine-id` unless pinned in netplan, so it changes on
     every fresh install — either pin it explicitly (add `macaddress: ...`
     under the interface in `/etc/netplan/*.yaml`) so it's stable across
     future reinstalls too, or update the router's reservation/port-forward
     to the new MAC and **verify reachability from outside the LAN**, not
     just locally (a local test can succeed via NAT hairpinning even when
     external access is actually broken).
   - From the Backup tab, click "Save & Init Repo" again (re-establishes
     `/root/.restic-password` on the new install) and re-run `backup.sh` /
     `full-system-backup.sh` once manually to confirm both are still
     working and re-establish the crontab entries if the restore didn't
     bring `etc/cron.d` and the root crontab back correctly.

7. **Run `harden-server.sh`.** The restored snapshot should already carry
   the SSH/UFW hardening (it's ordinary `/etc` config), but this confirms
   it — and it's a safe no-op if the snapshot already had it:
   ```
   sudo bash harden-server.sh
   ```

## If the NAS itself is also gone

This whole plan assumes the NAS survived (it's the offsite-from-the-server
half of the picture). If the NAS is also lost, there is currently no
secondary copy — that's a real gap, not something this backup solves.
