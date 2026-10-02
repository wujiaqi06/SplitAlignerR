"""P10 SETUP001 factory: exact P01 setup except subprocess-free arch identification."""
from pathlib import Path
import ctypes
import hashlib
import os
import re

import pidfd_primitives as p01


def construct_native_syscalls():
    """Return an exact P01 NativeSyscalls instance without invoking its __init__.

    The sole semantic substitution is built-in os.uname() sysname/machine in place
    of platform.system()/platform.machine(), avoiding platform.py's uname -p child.
    """
    observed = os.uname()
    p01.require(observed.sysname == 'Linux' and observed.machine == 'x86_64', 'UNSUPPORTED_ARCH')
    p01.require(ctypes.sizeof(ctypes.c_void_p) == 8 and ctypes.sizeof(ctypes.c_long) == 8
                and ctypes.sizeof(ctypes.c_int) == 4 and ctypes.sizeof(p01.SigAction) == 152
                and p01.SigAction.flags.offset == 136 and p01.SigAction.restorer.offset == 144,
                'UNSUPPORTED_ABI')
    files = ['/usr/include/x86_64-linux-gnu/asm/unistd_64.h',
             '/usr/include/x86_64-linux-gnu/bits/sigaction.h',
             '/usr/include/x86_64-linux-gnu/bits/types/__sigset_t.h']
    raw = {}
    for path in files:
        try:
            value = Path(path).read_bytes()
        except OSError as exc:
            raise p01.PidfdError('HEADER_UNAVAILABLE', path, exc.errno)
        p01.require(0 < len(value) <= 128 * 1024, 'HEADER_LENGTH')
        raw[path] = value

    def macro(data, name):
        matches = re.findall(rb'^\s*#\s*define\s+' + name + rb'\s+(0x[0-9a-fA-F]+|[0-9]+)\b',
                             data, re.M)
        p01.require(len(matches) == 1, 'HEADER_CONSTANT_AMBIGUOUS')
        return int(matches[0], 0)

    native = p01.NativeSyscalls.__new__(p01.NativeSyscalls)
    native.open_number = macro(raw[files[0]], b'__NR_pidfd_open')
    native.signal_number = macro(raw[files[0]], b'__NR_pidfd_send_signal')
    native.no_cldwait = macro(raw[files[1]], b'SA_NOCLDWAIT')
    p01.require((native.open_number, native.signal_number, native.no_cldwait) == (434, 424, 2),
                'UNSUPPORTED_HEADER_ABI')
    native.provenance = dict(
        platform='Linux-x86_64-LP64',
        header_files=[dict(path=key, bytes=len(value), sha256=hashlib.sha256(value).hexdigest())
                      for key, value in raw.items()],
        pidfd_open=native.open_number, pidfd_send_signal=native.signal_number,
        SA_NOCLDWAIT=native.no_cldwait, sizeof_sigaction=ctypes.sizeof(p01.SigAction),
        flags_offset=p01.SigAction.flags.offset, restorer_offset=p01.SigAction.restorer.offset,
        flags_supported=0)
    native.setup001_provenance = dict(
        factory='construct_native_syscalls',
        substitution='os.uname sysname/machine for platform.system/platform.machine only',
        os_uname_return=dict(sysname=observed.sysname, nodename=observed.nodename,
                             release=observed.release, version=observed.version,
                             machine=observed.machine),
        platform_private_cache_mutations=0, subprocess_imports=0, candidate_children=0,
        original_NativeSyscalls_init_invocations=0)
    native.libc = ctypes.CDLL(None, use_errno=True)
    native.libc.syscall.argtypes = (ctypes.c_long,)
    native.libc.syscall.restype = ctypes.c_long
    native.libc.sigaction.argtypes = (ctypes.c_int, ctypes.POINTER(p01.SigAction),
                                      ctypes.POINTER(p01.SigAction))
    native.libc.sigaction.restype = ctypes.c_int
    return native
