#!/bin/bash
# Dart Room launcher for the Mac (double-click it in Finder, or run: bash start-mac.command [options]).
#
# It checks Python, installs the camera libraries on first use, checks the port and the phone, starts the
# server and opens the Setup page in the default browser. Every option is passed on to server.py
# (for example --camera 192.168.1.23 or --record ~/dart-trial/session1), except:
#   --no-browser   do not open the Setup page automatically (same as DART_NO_BROWSER=1)
set -u
cd "$(dirname "$0")" || exit 1

say() { printf '%s\n' "$@"; }

# Show a plain-English problem and keep the window open when it was double-clicked.
fail() {
  say '' "  Dart Room could not start." '' "$@" ''
  if [ -t 0 ]; then read -r -p 'Press Return to close this window. ' || true; fi
  exit 1
}

# ---- options handled here ----
open_browser=1
[ -n "${DART_NO_BROWSER:-}" ] && open_browser=0
server_args=()
port=''
https=0
camera=''
previous=''
for arg in "$@"; do
  case "$arg" in
    --no-browser) open_browser=0; continue ;;
    --https) https=1 ;;
    --port=*) port="${arg#--port=}" ;;
    --camera=*) camera="${arg#--camera=}" ;;
  esac
  case "$previous" in
    --port) port="$arg" ;;
    --camera) camera="$arg" ;;
  esac
  previous="$arg"
  server_args+=("$arg")
done
if [ -z "$port" ]; then
  if [ "$https" = 1 ]; then port=8443; else port=8000; fi
fi

say '' \
  '  ===========================================' \
  '     D A R T   R O O M' \
  '  ===========================================' \
  '  Keep this window open while you play.' \
  '  To stop Dart Room, close this window or press Ctrl-C.' ''

# ---- Python 3.10 or newer ----
too_old='Dart Room needs Python 3.10 or newer.
  Download it from https://www.python.org/downloads/ , install it,
  then double-click start-mac.command again.'
if [ -n "${DART_PYTHON:-}" ]; then
  python_bin="$DART_PYTHON"
elif [ -x .venv/bin/python ]; then
  python_bin=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  python_bin=python3
else
  fail "  Python is not installed on this Mac. $too_old"
fi
if ! "$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  found="$("$python_bin" --version 2>&1 || true)"
  fail "  This Mac has ${found:-an old Python}. $too_old"
fi
if [ ! -x .venv/bin/python ]; then
  say '  Getting things ready for the first time…'
  "$python_bin" -m venv .venv ||
    fail '  Could not create the .venv folder here. Check that this folder is not read-only, then try again.'
fi
.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' ||
  fail "  The .venv folder was made with an old Python. Rename or delete the .venv folder. $too_old"

# Install on first use; later launches work offline when the installed versions still match.
if ! .venv/bin/python -c 'from importlib.metadata import version; import numpy, cv2; n=tuple(map(int,version("numpy").split(".")[:2])); c=tuple(map(int,version("opencv-python-headless").split(".")[:2])); assert (1,26)<=n<(3,0) and (4,10)<=c<(5,0)' >/dev/null 2>&1; then
  say '  Installing the camera libraries. This needs the Internet once and takes a few minutes…'
  .venv/bin/python -m pip install -r requirements.txt ||
    fail '  The camera libraries could not be downloaded.' \
         '  Check the Mac is connected to the Internet, then double-click start-mac.command again.'
fi

# ---- the port must be free ----
case "$port" in
  ''|*[!0-9]*) ;;  # not a number: server.py explains
  *)
    if ! .venv/bin/python - "$port" <<'PY' 2>/dev/null
import socket, sys
probe = socket.socket()
probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as the server does: a just-closed port is free
try:
    probe.bind(('0.0.0.0', int(sys.argv[1])))
finally:
    probe.close()
PY
    then
      fail "  Port $port is already in use. Dart Room is probably running already in another" \
           '  Terminal window: use that one, or close it and try again.' \
           "  (To run a second copy anyway, add --port $((port + 1)).)"
    fi
    ;;
esac

# ---- is the phone reachable? (a warning only: the server keeps trying by itself) ----
if [ -n "$camera" ]; then
  .venv/bin/python - "$camera" <<'PY' || true
import socket, sys
from urllib.parse import urlsplit
sys.path.insert(0, '.')
try:
    from camera_source import normalise_uri
    uri = normalise_uri(sys.argv[1])
except Exception as error:
    print(f'  Camera: {error}')
    sys.exit(0)
if uri.startswith('snapshot:'):
    uri = uri[len('snapshot:'):]
if uri.startswith(('http://', 'https://')):
    parts = urlsplit(uri)
    host, port = parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)
    try:
        socket.create_connection((host, port), timeout=3).close()
        print(f'  Phone found at {host}:{port}.')
    except OSError:
        print(f'  Cannot reach the phone at {host}:{port} yet.')
        print('  - On the phone, open IP Webcam and tap Start server (at the bottom).')
        print('  - Check the phone and this Mac are on the same Wi-Fi, and the numbers match the phone screen.')
        print('  Dart Room starts anyway and keeps trying; you can also change the address on the Setup page.')
PY
else
  say '  No phone address given: type it on the Setup page (step 1), or start with --camera PHONE_IP.'
fi
say ''

# ---- open the Setup page once the server prints its link ----
open_setup() {
  local url="$1"
  [ "$open_browser" = 1 ] || return 0
  if [ "$(uname -s)" = Darwin ] && command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 && say '  The Setup page is opening in your browser.' && return 0
  fi
  say '  Open the Setup link above in a browser on this Mac.'
}

# Pass the server's output through, watching for its "Setup:" line. The reader ignores Ctrl-C so the server
# can finish saving (and stop a recording) before the window's output pipe closes.
.venv/bin/python server.py "${server_args[@]+"${server_args[@]}"}" | {
  trap '' INT
  while IFS= read -r line; do
    printf '%s\n' "$line"
    case "$line" in
      'Setup:'*) open_setup "$(printf '%s' "${line#Setup:}" | tr -d ' ')" ;;
    esac
  done
}
status="${PIPESTATUS[0]}"
if [ "$status" != 0 ] && [ "$status" != 130 ]; then
  fail '  The message above says what went wrong.' \
       '  If it mentions the port, Dart Room may already be running in another window.'
fi
