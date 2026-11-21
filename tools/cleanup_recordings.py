"""Free the disk space recordings use on this Mac.

    .venv/bin/python tools/cleanup_recordings.py                 # list sessions and their sizes, delete nothing
    .venv/bin/python tools/cleanup_recordings.py --frames --yes  # delete the camera pictures, keep the small logs
    .venv/bin/python tools/cleanup_recordings.py --all --yes     # delete the whole session folders

Looks in ~/dart-trial and in the Dartgame folder's recordings/ (or the folders you name). --frames keeps the
text logs and the report (a few MB), so the session can still be summarised; --all removes everything.
Without --yes it only shows what it would delete.
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = [Path.home() / 'dart-trial', ROOT / 'recordings']
# Folders inside a session that hold pictures (the big part).
PICTURE_FOLDERS = ('frames',)


def size_of(path):
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())


def human(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


def sessions(roots):
    """Session folders: a folder holding session.json or frames/ (directly, or one level down)."""
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        candidates = [root] + sorted(p for p in root.iterdir() if p.is_dir())
        for folder in candidates:
            if (folder / 'session.json').exists() or (folder / 'frames').is_dir():
                found.append(folder)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folders', nargs='*', type=Path, help='session or parent folders (default: ~/dart-trial and recordings/)')
    what = parser.add_mutually_exclusive_group()
    what.add_argument('--frames', action='store_true', help='delete only the camera pictures (keeps logs and report)')
    what.add_argument('--all', action='store_true', help='delete the whole session folders')
    parser.add_argument('--yes', action='store_true', help='really delete (otherwise only show)')
    args = parser.parse_args(argv)
    found = sessions([folder.expanduser() for folder in args.folders] or DEFAULT_ROOTS)
    if not found:
        print('No recordings found. Nothing to clean up.')
        return 0
    total = freed = 0
    for folder in found:
        size = size_of(folder)
        total += size
        targets = [folder] if args.all else [folder / name for name in PICTURE_FOLDERS if (folder / name).exists()]
        target_size = sum(size_of(t) for t in targets) if (args.all or args.frames) else 0
        action = ''
        if args.all or args.frames:
            action = (' -> deleted ' if args.yes else ' -> would delete ') + human(target_size)
            if args.yes:
                for target in targets:
                    shutil.rmtree(target, ignore_errors=True)
                freed += target_size
        print(f'{folder}  {human(size)}{action}')
    print(f'Total {human(total)} in {len(found)} session folder(s).')
    if args.yes and (args.all or args.frames):
        print(f'Freed {human(freed)}.')
    elif args.all or args.frames:
        print('Nothing deleted yet: add --yes to delete.')
    else:
        print('Nothing deleted. Use --frames --yes (keep logs) or --all --yes (everything).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
