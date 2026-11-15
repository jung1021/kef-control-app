#!/usr/bin/env bash
# Builds the Microsoft Store package (KEFControl-<version>.msix) on Linux.
#
# 1. Build the normal installer first (it prepares installer/stage):   ../../installer/build.sh
# 2. Build Microsoft's makemsix tool once (https://github.com/microsoft/msix-packaging):
#      git clone --depth 1 https://github.com/microsoft/msix-packaging && cd msix-packaging
#      ./makelinux.sh --pack --skip-samples --skip-tests      (needs cmake >= 3.29, clang, libicu-dev)
#    and point MAKEMSIX at .vs/bin/makemsix.
# 3. Run with the values from Partner Center > your app > Product management > Product identity:
#      IDENTITY_NAME=12345Publisher.KEFControl PUBLISHER="CN=XXXXXXXX-...." \
#      PUBLISHER_DISPLAY_NAME="Your Name" MAKEMSIX=/path/to/makemsix ./build_msix.sh
#
# The package is unsigned on purpose: upload it to Partner Center and Microsoft signs it.
set -euo pipefail
cd "$(dirname "$0")"

: "${IDENTITY_NAME:?Set IDENTITY_NAME (Partner Center > Product identity > Package/Identity/Name)}"
: "${PUBLISHER:?Set PUBLISHER (Package/Identity/Publisher, e.g. CN=...)}"
: "${PUBLISHER_DISPLAY_NAME:?Set PUBLISHER_DISPLAY_NAME (Package/Properties/PublisherDisplayName)}"
MAKEMSIX="${MAKEMSIX:-makemsix}"

VERSION_SHORT=$(grep -oP '!define VERSION\s+"\K[0-9.]+' ../../installer/installer.nsi)
VERSION="${VERSION_SHORT}.0"
STAGE=../../installer/stage
[ -f "$STAGE/KEFControl.exe" ] || { echo "Run installer/build.sh first"; exit 1; }

LAYOUT=layout
rm -rf "$LAYOUT" && mkdir -p "$LAYOUT"
cp -r "$STAGE/app" "$STAGE/runtime" "$STAGE/KEFControl.exe" "$LAYOUT/"
cp -r Assets "$LAYOUT/"

echo "==> Tray launcher for the startup task"
x86_64-w64-mingw32-windres ../../installer/launcher.rc -O coff -o /tmp/kef-launcher.res
x86_64-w64-mingw32-gcc -municode -mwindows -O2 -s -DDEFAULT_ARGS='L"--background"' \
  -o "$LAYOUT/KEFControlTray.exe" ../../installer/launcher.c /tmp/kef-launcher.res

sed -e "s|@IDENTITY_NAME@|$IDENTITY_NAME|g" -e "s|@PUBLISHER@|$PUBLISHER|g" \
    -e "s|@PUBLISHER_DISPLAY_NAME@|$PUBLISHER_DISPLAY_NAME|g" -e "s|@VERSION@|$VERSION|g" \
    AppxManifest.xml.in > "$LAYOUT/AppxManifest.xml"

OUT="KEFControl-$VERSION_SHORT.msix"
rm -f "$OUT"
"$MAKEMSIX" pack -d "$LAYOUT" -p "$OUT"
ls -la "$OUT"
