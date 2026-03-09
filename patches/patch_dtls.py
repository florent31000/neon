"""Patch aiortc's rtcdtlstransport.py to handle missing DTLS_METHOD."""
import os
import sys

target = '/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/python-installs/neon/arm64-v8a/aiortc/rtcdtlstransport.py'

with open(target, 'r') as f:
    content = f.read()

old_import = 'from OpenSSL import SSL'

patch = '''from OpenSSL import SSL

# Patch: older pyOpenSSL versions lack DTLS_METHOD
if not hasattr(SSL, "DTLS_METHOD"):
    if hasattr(SSL, "DTLSv1_METHOD"):
        SSL.DTLS_METHOD = SSL.DTLSv1_METHOD
    else:
        try:
            from OpenSSL._util import lib as _lib
            if hasattr(_lib, "DTLS_method") or hasattr(_lib, "DTLSv1_method"):
                SSL.DTLS_METHOD = 7
            else:
                SSL.DTLS_METHOD = SSL.SSLv23_METHOD
        except Exception:
            SSL.DTLS_METHOD = SSL.SSLv23_METHOD'''

if old_import in content:
    content = content.replace(old_import, patch, 1)
    with open(target, 'w') as f:
        f.write(content)
    print('Patched rtcdtlstransport.py successfully')
else:
    if 'DTLS_METHOD' in content and 'Patch' in content:
        print('Already patched')
    else:
        print('ERROR: Could not find import line')
        print('First 300 chars:', content[:300])
        sys.exit(1)
