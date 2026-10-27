#!/bin/bash
set -e
cd "$(dirname "$0")"
fail() { printf '%s\n' "$1"; if [ -t 0 ]; then read -r -p 'Press Return to close. ' || true; fi; exit 1; }
if [ -n "${DART_PYTHON:-}" ]; then
  python_bin="$DART_PYTHON"
elif [ -x .venv/bin/python ]; then
  python_bin=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  python_bin=python3
else
  fail 'Python 3.10 or newer is required. Install Python from python.org and run this again.'
fi
"$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || fail 'Python 3.10 or newer is required. Install it from python.org, or set DART_PYTHON to its executable.'
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Creating the local Python environment…'
  "$python_bin" -m venv .venv || fail 'Could not create .venv. Check Python installation and write permission in this folder.'
fi
.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || fail 'The existing .venv uses an old Python. Rename .venv, then run again with Python 3.10 or newer.'
# Install on first use; later launches work offline when the installed versions still match.
if ! .venv/bin/python -c 'from importlib.metadata import version; import numpy, cv2; n=tuple(map(int,version("numpy").split(".")[:2])); c=tuple(map(int,version("opencv-python-headless").split(".")[:2])); assert (1,26)<=n<(3,0) and (4,10)<=c<(5,0)' >/dev/null 2>&1; then
  printf '%s\n' 'Installing camera dependencies. Internet access is needed for this first setup…'
  .venv/bin/python -m pip install -r requirements.txt || fail 'Dependency installation failed. Check Internet access, then run again.'
fi
printf '%s\n' 'Starting Dart Room. Keep this Terminal window open.' 'Open the Setup link below on this Mac; Controller and Presentation links work on other devices on your Wi-Fi.'
case " $* " in
  *" --camera "*|*" --camera="*) ;;
  *) printf '%s\n' 'Camera: add --camera PHONE_IP (IP Webcam), or enter the address on the Setup page.' ;;
esac
exec .venv/bin/python server.py "$@"
