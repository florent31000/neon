#!/bin/bash
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export JAVA_HOME="/usr"
echo "=== Buildozer version ==="
buildozer --version 2>&1
echo "=== Java version ==="
java -version 2>&1
echo "=== ADB check ==="
ls ~/.buildozer/android/platform/android-sdk/platform-tools/adb 2>/dev/null && echo "ADB found" || echo "ADB not found in SDK"
echo "=== Done ==="
