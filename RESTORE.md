# Bare-metal restore

How to rebuild this server from scratch using the full-system backup written
weekly to `/mnt/nas/wsbackup/fullsystem/<date>/` by `full-system-backup.sh`.
For everyday config-level recovery (an app's settings got corrupted, etc.),
use `backup.sh`'s snapshots at `/mnt/nas/wsbackup/mediaserver/<date>/`
instead — this document is for "the server itself is gone."

## What's in a snapshot

```
/mnt/nas/wsbackup/fullsystem/<YYYYMMDD>/
  root.tar.gz                # etc, home, root, opt, var, srv (see below)
  boot.tar.gz                # /boot and /boot/efi (nested), for reference
  system-info/
    dpkg-selections.txt      # `dpkg --get-selections` output
    apt-manual-packages.txt  # `apt-mark showmanual` output
    lsblk.txt, blkid.txt, parted.txt   # disk/partition layout reference
    docker-images.txt        # image:tag list that was present
```

`root.tar.gz` is a single tar archive rather than a mirrored directory tree —
the `wsbackup` CIFS share is mounted with `file_mode=0777,dir_mode=0777,
forceuid,forcegid`, which cannot represent real Unix permissions/ownership on
files written directly through it. A tar archive's internal entries preserve
permissions/ownership/ACLs correctly regardless of that (only the archive
file itself shows up as 0777 on the NAS, which doesn't matter); it's also far
faster than mirroring ~260k individual files over CIFS. It contains `etc`,
`home`, `root`, `opt`, `var`, and `srv` from the root filesystem — not `/usr`
(see step 3) and not `/boot` (backed up separately, see step 5).

Media library content (movies/tv/music/photos/etc. under `/mnt/nas/*`) is
**not** part of this backup — it already lives on the NAS, not on the
server's local disk, so it's unaffected by a server failure. A restored
server just needs its `/etc/fstab` (included in `root/etc/fstab`) to remount
those shares again.

## Restore procedure

1. **Install a minimal Ubuntu server** on the new/repaired hardware. Match
   the original release if possible (`system-info/lsblk.txt` and
   `parted.txt` from the snapshot show the original disk layout for
   reference, but you don't need to match partitioning exactly — just get a
   working base install with network access).

2. **Mount the NAS share** so you can reach the snapshot:
   ```
   sudo mkdir -p /mnt/nas/wsbackup
   sudo mount -t cifs //192.168.4.50/wsbackup /mnt/nas/wsbackup -o username=<user>
   ```
   (Or install `cifs-utils` first if it's not present: `sudo apt install cifs-utils`.)

3. **Reinstall the same packages** before restoring config files for them —
   this lets each package's postinst scripts set up its own package-manager
   bookkeeping cleanly, and matches the new install's own kernel/libc instead
   of relying on old copied binaries:
   ```
   SNAP=/mnt/nas/wsbackup/fullsystem/<pick-a-date>
   sudo apt update
   sudo xargs -a "$SNAP/system-info/apt-manual-packages.txt" apt install -y
   ```

4. **Restore everything else on top of the fresh install.** This extracts
   `etc`, `home`, `root`, `opt`, `var`, and `srv` back onto `/`, preserving
   the permissions/ownership/ACLs stored inside the archive:
   ```
   sudo tar --acls --xattrs -xzf "$SNAP/root.tar.gz" -C /
   ```

5. **Do not blindly overwrite `/boot` or `/boot/efi`** from `boot.tar.gz`.
   The fresh install already has a working bootloader/kernel for this
   hardware; the archive is there for reference (e.g. comparing GRUB config,
   recovering a specific file) rather than a wholesale restore. If you do
   need something from it: `tar xzf "$SNAP/boot.tar.gz" -C /tmp/boot-ref`
   and copy individual files by hand.

6. **Reboot**, then confirm:
   - `mount -a` remounts all the NAS shares from the restored `/etc/fstab`
     without errors.
   - `systemctl status emby-server sonarr radarr prowlarr bazarr sabnzbdplus`
     — services come up.
   - `docker ps` — containers restart (compose files were restored under
     `/opt/media/*`; images will be re-pulled automatically on
     `docker compose up` if they weren't already present locally, using
     `system-info/docker-images.txt` as a reference for what should exist).
   - Re-run `backup.sh` and `full-system-backup.sh` once manually
     (via the app's Backup tab, or `sudo /opt/media/backup.sh`) to confirm
     both are still working and re-establish the crontab entries if the
     restore didn't bring `etc/cron.d` and the root crontab back correctly.

## If the NAS itself is also gone

This whole plan assumes the NAS survived (it's the offsite-from-the-server
half of the picture). If the NAS is also lost, there is currently no
secondary copy — that's a real gap, not something this backup solves.
