"""Patch _validate_peer_identity for old pyOpenSSL without as_cryptography parameter."""

target = '/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/python-installs/neon/arm64-v8a/aiortc/rtcdtlstransport.py'

with open(target, 'r') as f:
    content = f.read()

old = '        certificate = self._ssl.get_peer_certificate(as_cryptography=True)'
new = '''        try:
            certificate = self._ssl.get_peer_certificate(as_cryptography=True)
        except TypeError:
            from OpenSSL import crypto as _crypto
            from cryptography.x509 import load_pem_x509_certificate
            from cryptography.hazmat.backends import default_backend
            ossl_cert = self._ssl.get_peer_certificate()
            if ossl_cert is not None:
                pem = _crypto.dump_certificate(_crypto.FILETYPE_PEM, ossl_cert)
                certificate = load_pem_x509_certificate(pem, default_backend())
            else:
                certificate = None'''

if old in content:
    content = content.replace(old, new)
    with open(target, 'w') as f:
        f.write(content)
    print("Patched get_peer_certificate")
else:
    print("WARNING: pattern not found")
