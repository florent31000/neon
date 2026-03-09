# ============================================
# BUILDOZER SPEC FILE FOR NEON
# ============================================
# Based on the working Rex buildozer.spec
# To build: buildozer android debug
# To deploy: buildozer android deploy run

[app]

title = Neon
package.name = neon
package.domain = com.neondog
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,yaml,txt,json
source.exclude_exts = spec
source.exclude_dirs = tests, bin, venv, .git, __pycache__, src/vendor/unitree_webrtc_connect/lidar

version = 0.1.0

# Requirements — based on the proven Rex list, trimmed to what Neon actually uses
requirements = python3,
    kivy==2.3.0,
    plyer,
    pyjnius,
    openssl,
    pyopenssl,
    numpy,
    aiortc,
    aioice,
    ifaddr,
    dnspython,
    av,
    pyee,
    pylibsrtp,
    google-crc32c,
    pillow,
    pyyaml,
    certifi,
    idna,
    typing_extensions,
    sniffio,
    anyio,
    h11,
    httpcore,
    httpx,
    requests,
    pycryptodome,
    cryptography,
    annotated_types,
    pydantic_core,
    pydantic,
    websocket-client,
    packaging

orientation = landscape

# Android NDK version
android.ndk = 25b
android.sdk = 35
android.api = 35
android.minapi = 26
android.ndk_api = 26
android.archs = arm64-v8a

# Permissions
android.permissions =
    INTERNET,
    ACCESS_NETWORK_STATE,
    ACCESS_WIFI_STATE,
    CHANGE_WIFI_STATE,
    CAMERA,
    RECORD_AUDIO,
    MODIFY_AUDIO_SETTINGS,
    WAKE_LOCK,
    FOREGROUND_SERVICE,
    VIBRATE,
    READ_EXTERNAL_STORAGE,
    WRITE_EXTERNAL_STORAGE

android.gradle_dependencies = androidx.core:core:1.6.0
android.apptheme = @android:style/Theme.NoTitleBar
android.accept_sdk_license = True
android.enable_androidx = True
fullscreen = 1

[buildozer]
log_level = 2
warn_on_root = 1

# Use the same build directory structure as Rex to reuse compiled deps
build_dir = /home/flore/.buildozer-neon
bin_dir = ./bin
