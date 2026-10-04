#!/bin/sh
# Build Luckbox.app into ~/Applications (or $1). Ad-hoc signed; macOS asks once to allow notifications.
set -e
DEST="${1:-$HOME/Applications}/Luckbox.app"
HERE="$(cd "$(dirname "$0")" && pwd)"
rm -rf "$DEST" && mkdir -p "$DEST/Contents/MacOS"
cat > "$DEST/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.luckbox.notifier</string>
  <key>CFBundleName</key><string>Luckbox</string>
  <key>CFBundleDisplayName</key><string>Luckbox</string>
  <key>CFBundleExecutable</key><string>Luckbox</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>CFBundleIconFile</key><string>AppIcon</string>
</dict></plist>
PLIST
swiftc -O -o "$DEST/Contents/MacOS/Luckbox" "$HERE/Notifier.swift" -framework Cocoa -framework UserNotifications

# Icon: draw once, then size it into an .icns
TMP="$(mktemp -d)"; SET="$TMP/AppIcon.iconset"; mkdir -p "$SET" "$DEST/Contents/Resources"
swift "$HERE/Icon.swift" "$TMP/icon.png"
for n in 16 32 128 256 512; do
  sips -z $n $n "$TMP/icon.png" --out "$SET/icon_${n}x${n}.png" >/dev/null
  sips -z $((n*2)) $((n*2)) "$TMP/icon.png" --out "$SET/icon_${n}x${n}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$DEST/Contents/Resources/AppIcon.icns"
cp "$TMP/icon.png" "$HERE/icon.png"
rm -rf "$TMP"
codesign --force --sign - "$DEST"
echo "$DEST"
