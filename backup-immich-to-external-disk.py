#!/usr/bin/env python3

'''
1. see if we're mounted
2. list existing backups, show space stats w/ a cool graphic
3. ask if we want to delete the oldest if we have >7 backups
4. use rsync to back up the relevant docker compose volumes
5. show stats of our most recent backup
'''

import argparse
import os
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

# Configuration
MOUNT_POINT = "/run/media/immich/immich-backup"
BACKUP_DIR = Path(MOUNT_POINT) / "immich-backups"
SOURCE_DIR = Path(__file__).parent.resolve()
VOLUMES_TO_BACKUP = ["library", "postgres"]
MAX_BACKUPS = 7


def is_mounted(path):
    return os.path.ismount(path)


def get_backups():
    if not BACKUP_DIR.exists():
        return []
    return sorted([d for d in BACKUP_DIR.iterdir() if d.is_dir()])


def show_space_bar(used, total, width=40):
    if total == 0:
        return "[" + "?" * width + "]"
    ratio = used / total
    filled = int(width * ratio)
    return f"[{'#' * filled}{'-' * (width - filled)}] {ratio * 100:.1f}%"


def show_disk_stats():
    usage = shutil.disk_usage(MOUNT_POINT)
    used_gb = usage.used / (1024**3)
    total_gb = usage.total / (1024**3)
    free_gb = usage.free / (1024**3)

    print(f"\nDisk: {MOUNT_POINT}")
    print(f"  {show_space_bar(usage.used, usage.total)}")
    print(f"  Used: {used_gb:.1f} GB / {total_gb:.1f} GB ({free_gb:.1f} GB free)")


def get_dir_size_gb(path):
    """Get directory size in GB using du -s."""
    result = subprocess.run(
        ["du", "-sb", str(path)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        size_bytes = int(result.stdout.split()[0])
        return size_bytes / (1024**3)
    return 0.0


def list_backups():
    backups = get_backups()
    if not backups:
        print("\nNo existing backups found.")
        return backups

    print(f"\nExisting backups ({len(backups)}):")
    for b in backups:
        size_gb = get_dir_size_gb(b)
        print(f"  {b.name}  ({size_gb:.2f} GB)")
    return backups


def maybe_delete_oldest():
    backups = get_backups()
    if len(backups) <= MAX_BACKUPS:
        return

    oldest = backups[0]
    print(f"\nYou have {len(backups)} backups (max {MAX_BACKUPS}).")
    response = input(f"Delete oldest backup '{oldest.name}'? [y/N] ").strip().lower()
    if response == 'y':
        print(f"Deleting {oldest.name}...")
        shutil.rmtree(oldest)
        print("Deleted.")


def stop_immich():
    print("\nStopping Immich containers...")
    subprocess.run(["docker", "compose", "stop"], cwd=SOURCE_DIR, check=True)


def start_immich():
    print("\nStarting Immich containers...")
    subprocess.run(["docker", "compose", "start"], cwd=SOURCE_DIR, check=True)


def check_today_exists():
    """Returns (dest_path, should_proceed)."""
    today = datetime.now().strftime("%Y-%m-%d")
    dest = BACKUP_DIR / today

    if dest.exists():
        print(f"\nBackup for today ({today}) already exists.")
        response = input("Overwrite? [y/N] ").strip().lower()
        if response != 'y':
            return dest, False

    return dest, True


def run_backup(dest):
    dest.mkdir(parents=True, exist_ok=True)

    print(f"\nBacking up to: {dest}")
    for vol in VOLUMES_TO_BACKUP:
        src = SOURCE_DIR / vol
        if not src.exists():
            print(f"  Skipping {vol} (not found)")
            continue
        print(f"  Syncing {vol}...")
        subprocess.run([
            "rsync", "-a", "--delete", "--info=progress2",
            str(src) + "/",
            str(dest / vol) + "/"
        ], check=True)


def show_backup_stats(backup_path):
    size_gb = get_dir_size_gb(backup_path)
    print(f"\nBackup complete: {backup_path.name} ({size_gb:.2f} GB)")


def main():
    parser = argparse.ArgumentParser(
        description="Backup Immich docker volumes to an external disk.",
        epilog="""
TO RESTORE FROM A BACKUP:
  1. Stop Immich:
       cd /home/immich/Git/cachyos-immich && docker compose stop

  2. Copy the backup folders back (replace YYYY-MM-DD with your backup date):
       sudo rsync -a --delete /run/media/immich/immich-backup/immich-backups/YYYY-MM-DD/library/ ./library/
       sudo rsync -a --delete /run/media/immich/immich-backup/immich-backups/YYYY-MM-DD/postgres/ ./postgres/

  3. Start Immich:
       docker compose start
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args()

    print("=== Immich Backup ===")

    # 0. Check root
    if os.geteuid() != 0:
        print("Error: This script must be run as root (sudo).")
        print("The Docker volumes are owned by root.")
        return 1

    # 1. Check mount
    if not is_mounted(MOUNT_POINT):
        print(f"Error: {MOUNT_POINT} is not mounted.")
        return 1

    # 2. Show stats and list backups
    show_disk_stats()
    list_backups()

    # 3. Maybe delete oldest
    maybe_delete_oldest()

    # 4. Check if today's backup exists
    backup_path, should_proceed = check_today_exists()
    if not should_proceed:
        print("Backup cancelled.")
        return 0

    # 5. Confirm before proceeding
    response = input("\nProceed with backup? [Y/n] ").strip().lower()
    if response == 'n':
        print("Backup cancelled.")
        return 0

    # 6. Stop, backup, start
    stop_immich()
    backup_failed = False
    try:
        run_backup(backup_path)
    except Exception:
        backup_failed = True
        raise
    finally:
        if backup_failed and backup_path.exists():
            print(f"\nBackup failed, cleaning up {backup_path}...")
            shutil.rmtree(backup_path)
        start_immich()

    # 7. Show final stats
    show_backup_stats(backup_path)
    show_disk_stats()

    return 0


if __name__ == "__main__":
    exit(main())
