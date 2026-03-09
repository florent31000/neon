"""Patch rtcdtlstransport.py to handle missing DTLSv1_get_timeout and DTLSv1_handle_timeout."""
import re

target = '/home/flore/.buildozer-neon/android/platform/build-arm64-v8a/build/python-installs/neon/arm64-v8a/aiortc/rtcdtlstransport.py'

with open(target, 'r') as f:
    content = f.read()

# Patch 1: Replace DTLSv1_get_timeout call with try/except
old_timeout = '''        # get timeout
        timeout = None
        if not self.encrypted:
            timeout = self._ssl.DTLSv1_get_timeout()'''

new_timeout = '''        # get timeout
        timeout = None
        if not self.encrypted:
            try:
                timeout = self._ssl.DTLSv1_get_timeout()
            except AttributeError:
                timeout = 1.0'''

if old_timeout in content:
    content = content.replace(old_timeout, new_timeout)
    print("Patched DTLSv1_get_timeout")
else:
    print("WARNING: DTLSv1_get_timeout pattern not found")

# Patch 2: Replace DTLSv1_handle_timeout call with try/except
old_handle = '                self._ssl.DTLSv1_handle_timeout()'
new_handle = '''                try:
                    self._ssl.DTLSv1_handle_timeout()
                except AttributeError:
                    pass'''

if old_handle in content:
    content = content.replace(old_handle, new_handle)
    print("Patched DTLSv1_handle_timeout")
else:
    print("WARNING: DTLSv1_handle_timeout pattern not found")

with open(target, 'w') as f:
    f.write(content)

print("Done")
