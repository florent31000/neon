"""Patch _setup_srtp for old pyOpenSSL without get_selected_srtp_profile."""

target = '/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/python-installs/neon/arm64-v8a/aiortc/rtcdtlstransport.py'

with open(target, 'r') as f:
    content = f.read()

old = '        openssl_profile = self._ssl.get_selected_srtp_profile()'
new = '''        try:
            openssl_profile = self._ssl.get_selected_srtp_profile()
        except AttributeError:
            # Old pyOpenSSL: use ctypes to call SSL_get_selected_srtp_profile
            import ctypes
            try:
                _libssl = ctypes.CDLL("libssl.so")
                from OpenSSL._util import ffi as _f
                ssl_ptr = _f.cast("intptr_t", self._ssl._ssl)
                ssl_addr = int(ssl_ptr)

                _libssl.SSL_get_selected_srtp_profile.restype = ctypes.c_void_p
                profile_ptr = _libssl.SSL_get_selected_srtp_profile(ctypes.c_void_p(ssl_addr))
                if profile_ptr:
                    # SRTP_PROTECTION_PROFILE struct: first field is name (const char *)
                    name_ptr = ctypes.cast(profile_ptr, ctypes.POINTER(ctypes.c_char_p))[0]
                    openssl_profile = name_ptr
                else:
                    openssl_profile = None
            except Exception:
                openssl_profile = b"SRTP_AES128_CM_SHA1_80"'''

if old in content:
    content = content.replace(old, new)
    with open(target, 'w') as f:
        f.write(content)
    print("Patched get_selected_srtp_profile")
else:
    print("WARNING: pattern not found (maybe already patched)")
