#!/usr/bin/env python3
"""드라이버의 정답지 (탐침 S0): PTX 를 NVIDIA 드라이버에 주고, 드라이버가 이 GPU 용으로 만든 기계어 파일(cubin)과
컴파일 기록(레지스터·스택)을 꺼낸다. CUDA 툴킷 없이 nvcuda.dll 만 쓴다. 재는 도구라 파이썬이다.

  python research/gpu/탐침/드라이버기계어.py <입력.ptx> [<출력.cubin>]

cubin 은 PTX 없이 그대로 GPU 에 올릴 수 있다 — 실행기.gl 에 PTX 대신 cubin 을 주면 드라이버는 로더 역할만 한다.
글이 SASS 를 직접 낼 때, 같은 커널에 대해 드라이버가 만든 이 cubin 이 바이트 대조의 정답지가 된다.
"""
import ctypes
import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CU_JIT_INFO_LOG_BUFFER, CU_JIT_INFO_LOG_BUFFER_SIZE_BYTES, CU_JIT_LOG_VERBOSE = 3, 4, 12
CU_JIT_INPUT_PTX = 1


def main(argv):
    if not argv:
        print(__doc__)
        return 3
    cu = ctypes.WinDLL("nvcuda.dll")
    if cu.cuInit(0) != 0:
        print("cuInit 실패")
        return 1
    dev = ctypes.c_int()
    cu.cuDeviceGet(ctypes.byref(dev), 0)
    ctx = ctypes.c_void_p()
    cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), dev)
    cu.cuCtxSetCurrent(ctx)
    ptx = open(argv[0], "rb").read() + b"\0"
    log = ctypes.create_string_buffer(16384)
    opts = (ctypes.c_int * 3)(CU_JIT_INFO_LOG_BUFFER, CU_JIT_INFO_LOG_BUFFER_SIZE_BYTES, CU_JIT_LOG_VERBOSE)
    vals = (ctypes.c_void_p * 3)(ctypes.cast(log, ctypes.c_void_p).value, 16384, 1)
    state = ctypes.c_void_p()
    steps = [
        cu.cuLinkCreate_v2(3, opts, vals, ctypes.byref(state)),
        cu.cuLinkAddData_v2(state, CU_JIT_INPUT_PTX, ptx, len(ptx), b"input.ptx", 0, None, None),
    ]
    image = ctypes.c_void_p()
    size = ctypes.c_size_t()
    steps.append(cu.cuLinkComplete(state, ctypes.byref(image), ctypes.byref(size)))
    if any(steps):
        print("드라이버 컴파일 실패:", steps)
        print(log.value.decode(errors="replace"))
        return 1
    data = ctypes.string_at(image, size.value)
    print(f"cubin {size.value} 바이트 ({'ELF' if data[:4] == b'\x7fELF' else '?'}), PTX 글자 {'있음' if b'.entry' in data else '없음'}")
    for line in log.value.decode(errors="replace").splitlines():
        if line.strip():
            print("  " + line.strip())
    if len(argv) > 1:
        open(argv[1], "wb").write(data)
        print(f"저장: {argv[1]}")
    cu.cuLinkDestroy(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
