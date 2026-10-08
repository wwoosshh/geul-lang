#!/usr/bin/env python3
"""제곱차 커널을 GPU 에서 돌려 x·x − x·x 가 0 인지 잰다 (docs/17 §7 PTX 계약 P1). CUDA 툴킷 없이 nvcuda.dll 만 쓴다.

  python research/gpu/탐침/제곱차재기.py <제곱차.ptx> [<커널 이름>]

첫째와 둘째에 같은 값을 넘기므로 글의 의미(곱해서 반올림, 빼서 반올림)로는 모든 칸이 정확히 0 이다. 드라이버가 곱과
뺄셈을 FMA 로 합치면 한쪽 곱만 반올림되어 0 이 아니게 되고, 음수가 나온 칸은 제곱근을 씌우면 NaN 이 된다.
재는 도구라 파이썬이다(드라이버기계어.py 와 같다). 0 이 아닌 칸이 하나라도 있으면 종료 코드 1.
"""
import array
import ctypes
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
N = 1 << 20


def ptx_name(name):
    """글ptx.py·쿠다.gl 과 같은 규칙: 라틴 이름은 그대로, 그 밖은 _G + UTF-8 16진수."""
    ok = name and (name[0].isascii() and (name[0].isalpha() or name[0] == "_")) and \
        all(c.isascii() and (c.isalnum() or c == "_") for c in name)
    return name if ok else "_G" + name.encode("utf-8").hex()


def check(code, what):
    if code != 0:
        raise SystemExit(f"쿠다 오류 {code}: {what}")


def main(argv):
    if not argv:
        print(__doc__)
        return 3
    name = ptx_name(argv[1] if len(argv) > 1 else "제곱차")
    cu = ctypes.WinDLL("nvcuda.dll")
    check(cu.cuInit(0), "cuInit")
    dev = ctypes.c_int()
    check(cu.cuDeviceGet(ctypes.byref(dev), 0), "cuDeviceGet")
    ctx = ctypes.c_void_p()
    check(cu.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), dev), "cuDevicePrimaryCtxRetain")
    check(cu.cuCtxSetCurrent(ctx), "cuCtxSetCurrent")
    mod = ctypes.c_void_p()
    check(cu.cuModuleLoadData(ctypes.byref(mod), open(argv[0], "rb").read() + b"\0"), "cuModuleLoadData")
    fn = ctypes.c_void_p()
    check(cu.cuModuleGetFunction(ctypes.byref(fn), mod, name.encode()), "cuModuleGetFunction")

    rng = random.Random(48)
    x = array.array("f", (rng.gauss(0.0, 1.0) for _ in range(N)))      # 짧은실수로 반올림되어 담긴다
    nbytes = N * 4
    first, second, out_dev = ctypes.c_uint64(), ctypes.c_uint64(), ctypes.c_uint64()
    for d in (first, second, out_dev):
        check(cu.cuMemAlloc_v2(ctypes.byref(d), ctypes.c_size_t(nbytes)), "cuMemAlloc")
    for d in (first, second):                                          # 같은 값, 다른 자리
        check(cu.cuMemcpyHtoD_v2(d, ctypes.c_void_p(x.buffer_info()[0]), ctypes.c_size_t(nbytes)), "cuMemcpyHtoD")
    n = ctypes.c_int64(N)
    params = [first, second, out_dev, n]
    args = (ctypes.c_void_p * 4)(*[ctypes.cast(ctypes.byref(p), ctypes.c_void_p) for p in params])
    check(cu.cuLaunchKernel(fn, N // 256, 1, 1, 256, 1, 1, 0, None, args, None), "cuLaunchKernel")
    check(cu.cuCtxSynchronize(), "cuCtxSynchronize")
    out = array.array("f", bytes(nbytes))
    check(cu.cuMemcpyDtoH_v2(ctypes.c_void_p(out.buffer_info()[0]), out_dev, ctypes.c_size_t(nbytes)), "cuMemcpyDtoH")
    for d in (first, second, out_dev):
        cu.cuMemFree_v2(d)
    cu.cuModuleUnload(mod)

    nonzero = sum(1 for v in out if v != 0.0)
    negative = sum(1 for v in out if v < 0.0)
    print(f"{argv[0]}: x·x − x·x 가 0 이 아닌 칸 {nonzero:,} / {N:,}, 그중 음수(제곱근이 NaN 이 되는 칸) {negative:,}")
    return 0 if nonzero == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
