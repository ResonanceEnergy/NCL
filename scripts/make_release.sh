#!/bin/bash
# Wave 14G Phase 7 — NCL Desktop release builder.
#
# 1. Archives NCLDesktop with Release config.
# 2. Code-signs with the DEVELOPMENT_TEAM cert.
# 3. Bundles as a .dmg with `create-dmg` (brew install create-dmg).
# 4. Computes Sparkle ed25519 signature via `sign_update`.
# 5. Drops files in ~/dev/NCL/data/desktop_releases/<version>/
#    + updates appcast.xml that Brain serves at /desktop/appcast.xml.
#
# Usage:
#   ./make_release.sh                  # bumps patch, e.g. 1.0.0 → 1.0.1
#   ./make_release.sh --version 1.2.0  # explicit version
#   ./make_release.sh --notarize       # also notarize via notarytool
#
# Pre-flight: ./setup_sparkle_keys.sh must have been run once + the
# returned public key pasted into project.yml.

set -e

PROJECT_ROOT="/Users/natrix/Projects/FirstStrike"
NCL_ROOT="$HOME/dev/NCL"
RELEASES_DIR="$NCL_ROOT/data/desktop_releases"
APPCAST="$RELEASES_DIR/appcast.xml"

mkdir -p "$RELEASES_DIR"

# Parse version
VERSION=""
NOTARIZE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="$2"; shift 2 ;;
        --notarize) NOTARIZE=1; shift ;;
        *) echo "unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$VERSION" ]]; then
    # Auto-bump: read MARKETING_VERSION from project.yml + bump patch
    CUR=$(grep MARKETING_VERSION "$PROJECT_ROOT/project.yml" | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')
    IFS=. read -r MA MI PA <<< "$CUR"
    VERSION="$MA.$MI.$((PA + 1))"
    echo "[make_release] auto-bumped $CUR → $VERSION"
fi

BUILD=$(date +%Y%m%d%H%M)
ARCHIVE="/tmp/ncl-desktop-${VERSION}.xcarchive"
EXPORT_DIR="/tmp/ncl-desktop-${VERSION}-export"
DMG="$RELEASES_DIR/NCLDesktop-${VERSION}.dmg"

cd "$PROJECT_ROOT"

# 1. Archive
echo "[make_release] archiving NCLDesktop ${VERSION} (${BUILD})…"
xcodebuild archive \
    -project FirstStrike.xcodeproj \
    -scheme NCLDesktop \
    -configuration Release \
    -archivePath "$ARCHIVE" \
    MARKETING_VERSION="$VERSION" \
    CURRENT_PROJECT_VERSION="$BUILD" \
    > /tmp/archive.log 2>&1 || { echo "ARCHIVE FAILED — see /tmp/archive.log"; tail -20 /tmp/archive.log; exit 1; }

# 2. Export with Developer ID Application signing
echo "[make_release] exporting…"
cat > /tmp/exportoptions.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key><string>developer-id</string>
    <key>teamID</key><string>N3C5G3SU3T</string>
    <key>signingStyle</key><string>automatic</string>
</dict>
</plist>
EOF

xcodebuild -exportArchive \
    -archivePath "$ARCHIVE" \
    -exportPath "$EXPORT_DIR" \
    -exportOptionsPlist /tmp/exportoptions.plist \
    > /tmp/export.log 2>&1 || { echo "EXPORT FAILED — see /tmp/export.log"; tail -20 /tmp/export.log; exit 1; }

APP_PATH="$EXPORT_DIR/NCL Desktop.app"

# 3. (Optional) notarize
if [[ $NOTARIZE -eq 1 ]]; then
    echo "[make_release] notarizing… (requires NOTARY_PROFILE env var)"
    NOTARY_ZIP=/tmp/ncl-notary.zip
    rm -f "$NOTARY_ZIP"
    ditto -c -k --keepParent "$APP_PATH" "$NOTARY_ZIP"
    xcrun notarytool submit "$NOTARY_ZIP" --keychain-profile "${NOTARY_PROFILE:-NCL}" --wait
    xcrun stapler staple "$APP_PATH"
fi

# 4. Build the .dmg
if ! command -v create-dmg &> /dev/null; then
    echo "[make_release] installing create-dmg…"
    brew install create-dmg
fi
rm -f "$DMG"
create-dmg \
    --volname "NCL Desktop ${VERSION}" \
    --window-pos 200 120 \
    --window-size 600 380 \
    --icon-size 100 \
    --icon "NCL Desktop.app" 150 180 \
    --app-drop-link 450 180 \
    --no-internet-enable \
    "$DMG" \
    "$EXPORT_DIR/" > /tmp/dmg.log 2>&1 || { echo "DMG BUILD FAILED — see /tmp/dmg.log"; tail -20 /tmp/dmg.log; exit 1; }

DMG_SIZE=$(stat -f%z "$DMG")
echo "[make_release] dmg size: $DMG_SIZE bytes"

# 5. Sparkle signature
# sign_update lives in the same dir as generate_keys
SIGN_UPDATE=""
PROBES=(
    /opt/homebrew/Caskroom/sparkle/*/bin/sign_update
    "$HOME"/Library/Developer/Xcode/DerivedData/*/SourcePackages/artifacts/sparkle/Sparkle/bin/sign_update
    "$HOME"/Library/Developer/Xcode/DerivedData/*/SourcePackages/checkouts/Sparkle/bin/sign_update
)
for p in "${PROBES[@]}"; do
    for r in $p; do
        if [[ -x "$r" ]]; then SIGN_UPDATE="$r"; break 2; fi
    done
done

if [[ -z "$SIGN_UPDATE" ]]; then
    echo "[make_release] WARN: sign_update not found. Appcast entry will be unsigned."
    SIG=""
else
    SIG=$("$SIGN_UPDATE" "$DMG")
    echo "[make_release] sparkle signature: $SIG"
fi

# 6. Generate / update appcast.xml
PUBDATE=$(date -R)
ENTRY=$(cat <<EOF
        <item>
            <title>Version $VERSION</title>
            <pubDate>$PUBDATE</pubDate>
            <sparkle:version>$BUILD</sparkle:version>
            <sparkle:shortVersionString>$VERSION</sparkle:shortVersionString>
            <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
            <enclosure
                url="http://100.72.223.123:8800/desktop/dl/NCLDesktop-${VERSION}.dmg"
                length="$DMG_SIZE"
                type="application/octet-stream"
                $SIG
            />
        </item>
EOF
)

if [[ ! -f "$APPCAST" ]]; then
    cat > "$APPCAST" <<EOF
<?xml version="1.0" standalone="yes"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     version="2.0">
    <channel>
        <title>NCL Desktop</title>
        <link>http://100.72.223.123:8800/desktop/appcast.xml</link>
        <description>NCL Desktop release feed</description>
        <language>en</language>
$ENTRY
    </channel>
</rss>
EOF
    echo "[make_release] created $APPCAST"
else
    # Insert new <item> right after the <channel> opener
    python3 -c "
import re
p = '$APPCAST'
s = open(p).read()
entry = '''$ENTRY'''
s = re.sub(r'(<channel>[^<]*)', r'\\1\n' + entry, s, count=1)
open(p, 'w').write(s)
print('appended to', p)
"
fi

echo ""
echo "[make_release] DONE"
echo "  archive: $ARCHIVE"
echo "  app:     $APP_PATH"
echo "  dmg:     $DMG"
echo "  appcast: $APPCAST"
echo ""
echo "  Sparkle clients will pick this up at next /system/ops/stream refresh."
echo "  Brain serves the dmg via GET /desktop/dl/NCLDesktop-${VERSION}.dmg"
echo "  and the appcast via GET /desktop/appcast.xml."
