#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD="$ROOT/build"
PKG="dev/thndang/aovcollector/adbime"
ANDROID_JAR="$ANDROID_HOME/platforms/android-35/android.jar"
BT="$(find "$ANDROID_HOME/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -n 1)"

rm -rf "$BUILD"
mkdir -p "$BUILD/classes" "$BUILD/dex" "$BUILD/compiled"

"$BT/aapt2" compile --dir "$ROOT/res" -o "$BUILD/compiled/resources.zip"

javac   -source 11   -target 11   -classpath "$ANDROID_JAR"   -d "$BUILD/classes"   "$ROOT/src/$PKG/AdbIme.java"

"$BT/d8"   --lib "$ANDROID_JAR"   --min-api 23   --output "$BUILD/dex"   "$BUILD/classes/$PKG/AdbIme.class"   "$BUILD/classes/$PKG/AdbIme\$1.class"

"$BT/aapt2" link   -o "$BUILD/unsigned.apk"   -I "$ANDROID_JAR"   --manifest "$ROOT/AndroidManifest.xml"   --min-sdk-version 23   --target-sdk-version 35   "$BUILD/compiled/resources.zip"

(
  cd "$BUILD/dex"
  zip -q -j "$BUILD/unsigned.apk" classes.dex
)

if [ ! -f "$BUILD/debug.keystore" ]; then
  keytool -genkeypair     -keystore "$BUILD/debug.keystore"     -storepass android     -keypass android     -alias androiddebugkey     -dname "CN=Android Debug,O=Android,C=US"     -keyalg RSA     -keysize 2048     -validity 10000     >/dev/null 2>&1
fi

"$BT/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

"$BT/apksigner" sign   --ks "$BUILD/debug.keystore"   --ks-pass pass:android   --key-pass pass:android   --out "$BUILD/adb-ime.apk"   "$BUILD/aligned.apk"

echo "$BUILD/adb-ime.apk"
