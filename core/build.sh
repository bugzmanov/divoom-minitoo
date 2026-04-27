#!/bin/bash
set -euo pipefail

# Builds divoom-send as a minimal .app bundle so macOS will grant Bluetooth access.
# First run triggers a one-time permission prompt; subsequent runs are silent.

APP="divoom-send.app"
BIN="divoom-send"

swiftc -o "$BIN" divoom-send.swift

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/$BIN"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>divoom-send</string>
    <key>CFBundleIdentifier</key>
    <string>local.divoom.send</string>
    <key>CFBundleName</key>
    <string>divoom-send</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSBluetoothAlwaysUsageDescription</key>
    <string>Send display commands to the Divoom Minitoo.</string>
    <key>NSBluetoothPeripheralUsageDescription</key>
    <string>Send display commands to the Divoom Minitoo.</string>
</dict>
</plist>
PLIST

codesign --force --sign - --deep "$APP"
echo "Built: $APP"
echo "Run:   ./$APP/Contents/MacOS/$BIN <MAC> face <id>"
