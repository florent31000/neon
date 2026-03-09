#!/bin/bash
set -e
NDK="/home/flore/.buildozer/android/platform/android-ndk-r25b"
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
CC="$TOOLCHAIN/bin/aarch64-linux-android26-clang"

LIBSRTP_DIR="/tmp/libsrtp-2.5.0"
PY_INC="/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/other_builds/hostpython3/desktop/hostpython3/Include"
PY_BUILD="/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/other_builds/hostpython3/desktop/hostpython3/native-build"
NEON_LIBS="/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/libs_collections/neon/arm64-v8a"

cd /tmp/pylibsrtp-0.10.0

# Compile the C source to .o
$CC -fPIC -c \
    -I$LIBSRTP_DIR/include \
    -I$PY_INC -I$PY_BUILD \
    -o /tmp/_binding.o \
    src/pylibsrtp/_binding.c

# Link into .so
$CC -shared \
    -o /tmp/_binding.abi3.so \
    /tmp/_binding.o \
    $LIBSRTP_DIR/libsrtp2.a \
    -L$NEON_LIBS -lcrypto1.1 \
    -lm -llog

file /tmp/_binding.abi3.so
echo "DONE"
