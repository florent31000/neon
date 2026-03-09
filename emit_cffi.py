import sys
sys.path.insert(0, 'src')
from _cffi_src.build_srtp import ffibuilder
ffibuilder.emit_c_code('src/pylibsrtp/_binding.c')
print('C source emitted')
