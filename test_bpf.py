import struct
import ctypes
import os
import sys

BPF_LD_W_ABS = 0x20
BPF_JMP_JEQ_K = 0x15
BPF_RET_K = 0x06

SECCOMP_RET_ERRNO = 0x00050000 | 1
SECCOMP_RET_ALLOW = 0x7fff0000

class sock_filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16),
                ("jt", ctypes.c_uint8),
                ("jf", ctypes.c_uint8),
                ("k", ctypes.c_uint32)]

class sock_fprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort),
                ("filter", ctypes.POINTER(sock_filter))]

def apply_seccomp(blocked):
    filters = []
    # Load syscall nr
    filters.append(sock_filter(BPF_LD_W_ABS, 0, 0, 0))
    for sc in blocked:
        filters.append(sock_filter(BPF_JMP_JEQ_K, 0, 1, sc))
        filters.append(sock_filter(BPF_RET_K, 0, 0, SECCOMP_RET_ERRNO))
    filters.append(sock_filter(BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW))
    
    FilterArray = sock_filter * len(filters)
    filter_array = FilterArray(*filters)
    prog = sock_fprog(len(filters), filter_array)
    
    libc = ctypes.CDLL(None, use_errno=True)
    
    # PR_SET_NO_NEW_PRIVS = 38
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        err = ctypes.get_errno()
        print(f"prctl(NO_NEW_PRIVS) failed: {err}")
        return
        
    # PR_SET_SECCOMP = 22, SECCOMP_MODE_FILTER = 2
    if libc.prctl(22, 2, ctypes.byref(prog)) != 0:
        err = ctypes.get_errno()
        print(f"prctl(SECCOMP) failed: {err}")
        return
    print("Seccomp applied!")

apply_seccomp([165]) # mount
print("Calling mount (should fail with EPERM)")
libc = ctypes.CDLL(None, use_errno=True)
res = libc.mount(b"none", b"/tmp", b"tmpfs", 0, None)
if res != 0:
    print(f"mount returned {res}, errno={ctypes.get_errno()}")
