#!/usr/bin/env bash
# Build VPN Pulse Probe into a signed debug APK with nothing but a JDK and the Android SDK:
#
#   aapt2 compile -> aapt2 link -> javac -> jar -> d8 -> jar uf -> zipalign -> apksigner
#
# No Gradle, no Kotlin, no AndroidX, no downloads. Same chain as android/spike/build.sh, with
# real resources (values/, values-night/, values-ru/, drawable/ …) and a generated R.java.
#
#   ./build.sh            build build/vpn-pulse-probe.apk
#   ./build.sh install    build, then install on the attached phone (adb install -r)
#   ./build.sh clean      remove build/
#
# Needs: JDK 17 (javac, jar, keytool), Android SDK build-tools 36 and platform 35. Override with
# ANDROID_SDK_ROOT / ANDROID_HOME, BUILD_TOOLS, ANDROID_JAR. JAVA_SRC overrides the source root
# (used to prove the chain against a throwaway activity without touching src/).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
APP="$HERE/app"
MANIFEST="${MANIFEST:-$APP/src/main/AndroidManifest.xml}"
RES="${RES_DIR:-$APP/src/main/res}"
JAVA_SRC="${JAVA_SRC:-$APP/src/main/java}"
BUILD="${BUILD_DIR:-$HERE/build}"
APK_NAME="${APK_NAME:-vpn-pulse-probe}"
PKG="dev.vpnpulse.probe"

SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}}"
BT="${BUILD_TOOLS:-$SDK/build-tools/36.0.0}"
AJ="${ANDROID_JAR:-$SDK/platforms/android-35/android.jar}"

MIN_SDK=26
TARGET_SDK=35

# keep the keystore: a full reinstall gives the app a new UID, and the VPN client's
# split-tunnelling exclusion then still applies to the old one until the tunnel is reconnected.
# Same key for every build => `adb install -r` upgrades in place and the exclusion survives.
KS_DIR="$HERE/.keystore"
KS="$KS_DIR/debug.keystore"
KS_PASS=android
KS_ALIAS=debug

if [ "${1:-}" = "clean" ]; then rm -rf "$BUILD"; echo "cleaned: $BUILD"; exit 0; fi

# --- the toolchain -----------------------------------------------------------------------------
# build-tools binaries are `aapt2.exe` / `d8.bat` on Windows and extensionless on Linux and macOS;
# bash will not find `d8` by itself on Windows, and it cannot exec a .bat without the suffix.
sdk_tool() {
    local n
    for n in "$1" "$1.exe" "$1.bat"; do
        if [ -f "$BT/$n" ]; then printf '%s\n' "$BT/$n"; return 0; fi
    done
    echo "build-tools binary not found: $1 (looked in $BT)" >&2
    return 1
}
# Two shapes of path are needed on Windows, and neither is the MSYS one:
#   nat()     backslashes, for aapt2 — it reads the resource type out of the parent folder name
#             and splits on the native separator, so `C:/…/res/values/colors.xml` (what MSYS
#             hands it) fails with "bad resource path". Native tools, so MSYS rewrites nothing.
#   winpath() forward slashes, for javac @argfiles and `jar -C`, which the tools read themselves
#             and MSYS therefore never sees. A backslash in an argfile is an escape character.
# Both are identity on Linux and macOS, where cygpath does not exist.
nat()     { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s\n' "$1"; fi; }
winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi; }

[ -f "$AJ" ] || { echo "android.jar not found: $AJ (set ANDROID_SDK_ROOT)" >&2; exit 2; }
[ -d "$BT" ] || { echo "build-tools not found: $BT (set BUILD_TOOLS)" >&2; exit 2; }
[ -f "$MANIFEST" ] || { echo "manifest not found: $MANIFEST" >&2; exit 2; }
[ -d "$RES" ] || { echo "resources not found: $RES" >&2; exit 2; }
AAPT2=$(sdk_tool aapt2)
D8=$(sdk_tool d8)
ZIPALIGN=$(sdk_tool zipalign)
APKSIGNER=$(sdk_tool apksigner)

FLAT="$BUILD/flat"; GEN="$BUILD/gen"; CLASSES="$BUILD/classes"; DEX="$BUILD/dex"
rm -rf "$FLAT" "$GEN" "$CLASSES" "$DEX" \
       "$BUILD/classes.jar" "$BUILD/classes.dex" "$BUILD/base.apk" "$BUILD/aligned.apk" "$BUILD/$APK_NAME.apk"
mkdir -p "$FLAT" "$GEN" "$CLASSES" "$DEX"

# --- 1. resources ------------------------------------------------------------------------------
# every file under res/ becomes one .flat; aapt2 names them after the qualified folder
# (values_colors.arsc.flat, values-night_colors.arsc.flat, drawable_ring.xml.flat …)
RES_FILES=()
while IFS= read -r f; do RES_FILES+=("$(nat "$f")"); done < <(find "$RES" -type f ! -name '.*' | sort)
[ "${#RES_FILES[@]}" -gt 0 ] || { echo "no resource files under $RES" >&2; exit 2; }
"$AAPT2" compile -o "$(nat "$FLAT")" "${RES_FILES[@]}"

FLAT_FILES=()
while IFS= read -r f; do FLAT_FILES+=("$(nat "$f")"); done < <(find "$FLAT" -name '*.flat' | sort)
# --java: R.java for $PKG, read by the sources below. No --proguard, no --emit-ids: debug build.
"$AAPT2" link -o "$(nat "$BUILD/base.apk")" -I "$(nat "$AJ")" \
    --manifest "$(nat "$MANIFEST")" --java "$(nat "$GEN")" \
    --min-sdk-version "$MIN_SDK" --target-sdk-version "$TARGET_SDK" \
    --no-version-vectors \
    `# minSdk 26: vector drawables are native, so no version-qualified PNG fallbacks` \
    "${FLAT_FILES[@]}"

# --- 2. java -----------------------------------------------------------------------------------
# checked on its own: with only the generated R.java the chain still produces a signed APK, and
# one without MainActivity in it is worse than a build failure
[ -d "$JAVA_SRC" ] || { echo "no java source root: $JAVA_SRC (set JAVA_SRC=... to build elsewhere)" >&2; exit 2; }
SRCS=()
while IFS= read -r f; do SRCS+=("$f"); done < <(find "$JAVA_SRC" -name '*.java' | sort)
[ "${#SRCS[@]}" -gt 0 ] || { echo "no .java sources under $JAVA_SRC" >&2; exit 2; }
while IFS= read -r f; do SRCS+=("$f"); done < <(find "$GEN" -name '*.java' | sort)
# an argfile, because a full source list blows past Windows' 8191-character command line
: > "$BUILD/sources.txt"
for f in "${SRCS[@]}"; do winpath "$f" >> "$BUILD/sources.txt"; done
# -encoding UTF-8: never depend on the machine's code page (Windows still defaults to cp1251/1252)
javac -encoding UTF-8 --release 11 -nowarn \
    -classpath "$AJ" -d "$CLASSES" "@$(winpath "$BUILD/sources.txt")"

# --- 3. dex ------------------------------------------------------------------------------------
# via a jar: d8 takes the archive in one argument, so neither the class list nor the command line
# can get too long (and R$string, R$color … inner classes cannot be missed)
jar --create --file "$BUILD/classes.jar" -C "$(winpath "$CLASSES")" .
"$D8" --release --min-api "$MIN_SDK" --lib "$AJ" --output "$DEX" "$BUILD/classes.jar"

# --- 4. package, align, sign -------------------------------------------------------------------
cp "$DEX/classes.dex" "$BUILD/classes.dex"
# `jar` names the entry after the path it is given: run it from $BUILD so the entry is classes.dex
( cd "$BUILD" && jar --update --file base.apk classes.dex )
# -p 4: page-align uncompressed entries (resources.arsc must stay stored and aligned for
# targetSdk 30+). Align before signing; apksigner preserves the alignment, zipalign would not
# preserve the signature.
"$ZIPALIGN" -f -p 4 "$BUILD/base.apk" "$BUILD/aligned.apk"
if [ ! -f "$KS" ]; then
    mkdir -p "$KS_DIR"
    keytool -genkeypair -keystore "$KS" -storepass "$KS_PASS" -keypass "$KS_PASS" \
        -alias "$KS_ALIAS" -keyalg RSA -keysize 2048 -validity 10950 \
        -dname "CN=VPN Pulse Probe Debug, O=VPN Pulse, C=LV"
    echo "created keystore: $KS (keep it — a new key means a new UID on reinstall)"
fi
"$APKSIGNER" sign --ks "$KS" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
    --ks-key-alias "$KS_ALIAS" --min-sdk-version "$MIN_SDK" \
    --out "$BUILD/$APK_NAME.apk" "$BUILD/aligned.apk"
"$APKSIGNER" verify --min-sdk-version "$MIN_SDK" "$BUILD/$APK_NAME.apk"
"$ZIPALIGN" -c -v 4 "$BUILD/$APK_NAME.apk" >/dev/null
echo "built: $BUILD/$APK_NAME.apk"

if [ "${1:-}" = "install" ]; then
    # -r: upgrade in place, keeping the UID and the split-tunnelling exclusion
    adb install -r "$BUILD/$APK_NAME.apk"
    adb shell am start -n "$PKG/.MainActivity"
fi
