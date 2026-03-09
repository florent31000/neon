try:
    from OpenSSL._util import lib
    dtls_attrs = [x for x in dir(lib) if 'DTLS' in x or 'dtls' in x or 'Dtls' in x]
    print(f"DTLS attrs in lib: {dtls_attrs}")
except Exception as e:
    print(f"Error: {e}")

try:
    from OpenSSL import SSL
    print(f"SSLv23_METHOD: {SSL.SSLv23_METHOD}")
    print(f"Has DTLS_METHOD: {hasattr(SSL, 'DTLS_METHOD')}")
    print(f"Has DTLSv1_METHOD: {hasattr(SSL, 'DTLSv1_METHOD')}")
except Exception as e:
    print(f"SSL Error: {e}")
