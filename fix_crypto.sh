#!/bin/bash
cd /home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/python-installs/neon/arm64-v8a/Crypto/Util/
python3 -m py_compile number.py
cp __pycache__/number.cpython-*.pyc /home/flore/.buildozer-neon/android/platform/build-arm64-v8a/dists/neon/_python_bundle__arm64-v8a/_python_bundle/site-packages/Crypto/Util/number.pyc

# Also check for other missing .pyc files
SRC=/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/python-installs/neon/arm64-v8a/Crypto/Util
DST=/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/dists/neon/_python_bundle__arm64-v8a/_python_bundle/site-packages/Crypto/Util

for f in $SRC/*.py; do
    base=$(basename "$f" .py)
    if [ ! -f "$DST/${base}.pyc" ]; then
        echo "Missing: ${base}.pyc — compiling and copying"
        python3 -m py_compile "$f"
        cp "$SRC/__pycache__/${base}.cpython-"*.pyc "$DST/${base}.pyc" 2>/dev/null
    fi
done

echo "DONE"
