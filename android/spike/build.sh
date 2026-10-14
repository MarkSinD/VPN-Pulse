#!/usr/bin/env bash
# Build and install the R-19 spike without Gradle: aapt2 -> javac -> d8 -> zipalign -> apksigner.
# Needs a JDK (17), the Android SDK (build-tools 36, platform 35) and, for `install`, adb.
#   ./build.sh              build out/vpn-pulse-spike.apk
#   ./build.sh install      build, then install on the attached phone
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}}"
BT="${BUILD_TOOLS:-$SDK/build-tools/36.0.0}"
AJ="${ANDROID_JAR:-$SDK/platforms/android-35/android.jar}"
OUT="$HERE/out"
[ -f "$AJ" ] || { echo "android.jar not found: $AJ (set ANDROID_SDK_ROOT)" >&2; exit 2; }

rm -rf "$OUT/classes" "$OUT/dex" "$OUT/base.apk" "$OUT/aligned.apk"
mkdir -p "$OUT/classes" "$OUT/dex"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$AJ" --manifest "$HERE/AndroidManifest.xml" --min-sdk-version 26 --target-sdk-version 35
# -encoding UTF-8: the source carries Russian strings and javac would otherwise read them in the platform encoding
javac -encoding UTF-8 --release 11 -nowarn -classpath "$AJ" -d "$OUT/classes" "$HERE/src/dev/vpnpulse/spike/MainActivity.java"
"$BT/d8" --release --min-api 26 --lib "$AJ" --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
cp "$OUT/dex/classes.dex" "$OUT/classes.dex"
( cd "$OUT" && jar uf base.apk classes.dex )          # `jar` names the entry after the path: run from here
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$OUT/aligned.apk"   # align before signing; apksigner preserves it
# keep the keystore: a full reinstall gives the app a new UID and Amnezia's split-tunnelling exclusion
# then applies to the old one until the tunnel is reconnected
[ -f "$OUT/spike.keystore" ] || keytool -genkeypair -keystore "$OUT/spike.keystore" -storepass android -keypass android \
  -alias spike -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=VPN Pulse Spike, O=VPN Pulse, C=LV"
"$BT/apksigner" sign --ks "$OUT/spike.keystore" --ks-pass pass:android --key-pass pass:android --ks-key-alias spike \
  --min-sdk-version 26 --out "$OUT/vpn-pulse-spike.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify "$OUT/vpn-pulse-spike.apk" && echo "built: $OUT/vpn-pulse-spike.apk"
[ "${1:-}" = "install" ] && adb install -r "$OUT/vpn-pulse-spike.apk" && adb shell am start -n dev.vpnpulse.spike/.MainActivity
