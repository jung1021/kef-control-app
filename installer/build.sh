#!/usr/bin/env bash
# Builds KEFControl-Setup-<version>.exe on Linux (no Windows needed).
#
# Requirements (Debian/Ubuntu):
#   sudo apt install nsis gcc-mingw-w64-x86-64 binutils-mingw-w64-x86-64 python3-pip unzip curl
#
# Usage:  cd installer && ./build.sh
set -euo pipefail
cd "$(dirname "$0")"

PY_VERSION="${PY_VERSION:-3.13.17}"
CACHE=cache
STAGE=stage
mkdir -p "$CACHE"

echo "==> Python $PY_VERSION embeddable runtime"
EMBED="$CACHE/python-$PY_VERSION-embed-amd64.zip"
[ -f "$EMBED" ] || curl -fsSL -o "$EMBED" "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip"

echo "==> Windows wheels"
rm -rf "$CACHE/wheels" && mkdir -p "$CACHE/wheels"
python3 -m pip download -q -d "$CACHE/wheels" --platform win_amd64 \
  --python-version "${PY_VERSION%.*}" --implementation cp --only-binary=:all: \
  -r ../src/requirements.txt

echo "==> Staging"
rm -rf "$STAGE" && mkdir -p "$STAGE/runtime/Lib/site-packages" "$STAGE/app"
unzip -q "$EMBED" -d "$STAGE/runtime"
for w in "$CACHE"/wheels/*.whl; do unzip -q -o "$w" -d "$STAGE/runtime/Lib/site-packages"; done
# python-xlib is only used by pystray on Linux
rm -rf "$STAGE"/runtime/Lib/site-packages/Xlib "$STAGE"/runtime/Lib/site-packages/python_xlib*
PTH=$(ls "$STAGE"/runtime/python3*._pth)
ZIP=$(basename "$(ls "$STAGE"/runtime/python3*.zip)")
printf '%s\r\n.\r\nLib\\site-packages\r\n..\\app\r\n' "$ZIP" > "$PTH"
cp ../src/kef_control.py ../src/tray.py ../src/powersync.py ../src/ui.html ../src/kef_control.ico "$STAGE/app/"

echo "==> Precompiling Python files (faster start-up)"
if python3 -c "import sys; sys.exit(0 if '%d.%d' % sys.version_info[:2] == '${PY_VERSION%.*}' else 1)"; then
  python3 -m compileall -q -j 0 --invalidation-mode unchecked-hash "$STAGE/runtime/Lib/site-packages" "$STAGE/app" >/dev/null
else
  echo "    (skipped: host Python is not ${PY_VERSION%.*})"
fi

echo "==> Launcher (KEFControl.exe)"
x86_64-w64-mingw32-windres launcher.rc -O coff -o launcher.res
x86_64-w64-mingw32-gcc -municode -mwindows -O2 -s -o "$STAGE/KEFControl.exe" launcher.c launcher.res

echo "==> Installer"
makensis -V2 installer.nsi
ls -la KEFControl-Setup-*.exe
