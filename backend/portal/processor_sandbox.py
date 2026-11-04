"""Additional Linux restrictions for untrusted parsers; inherited by their child programs."""
import ctypes
import ctypes.util
import errno
import sys


def restrict_parser():
    if sys.platform!='linux':raise RuntimeError('The file processor requires Linux')
    # Minimal musl images lack the ldconfig/compiler helpers used by find_library.
    # Let the system loader resolve the installed ABI; failure still rejects work.
    path=ctypes.util.find_library('seccomp') or 'libseccomp.so.2'
    libc=ctypes.CDLL(None,use_errno=True)
    libc.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong]
    if libc.prctl(38,1,0,0,0)!=0:raise RuntimeError('Cannot set no_new_privs')
    try:
        library=ctypes.CDLL(path,use_errno=True)
    except OSError:
        raise RuntimeError('libseccomp is required') from None
    library.seccomp_init.argtypes=[ctypes.c_uint32];library.seccomp_init.restype=ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];library.seccomp_syscall_resolve_name.restype=ctypes.c_int
    library.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
    library.seccomp_load.argtypes=[ctypes.c_void_p]
    library.seccomp_release.argtypes=[ctypes.c_void_p]
    context=library.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW, deny sensitive operations below.
    if not context:raise RuntimeError('Cannot create parser filter')
    try:
        blocked=['socket','socketpair','connect','accept','accept4','bind','listen','sendto','sendmsg','sendmmsg','recvfrom','recvmsg','recvmmsg','ptrace','process_vm_readv','process_vm_writev','pidfd_open','pidfd_getfd','pidfd_send_signal','kill','tkill','tgkill','setsid','setpgid','unshare','setns','bpf','io_uring_setup','io_uring_register','io_uring_enter']
        for name in blocked:
            number=library.seccomp_syscall_resolve_name(name.encode())
            if number>=0 and library.seccomp_rule_add(context,0x00050000|errno.EPERM,number,0)!=0:raise RuntimeError('Cannot restrict parser syscall')
        if library.seccomp_load(context)!=0:raise RuntimeError('Cannot apply parser filter')
    finally:library.seccomp_release(context)
