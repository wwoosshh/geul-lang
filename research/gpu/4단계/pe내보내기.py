#!/usr/bin/env python3
"""4단계 — DLL 이 내보내는 함수 이름을 PE 파일에서 읽는다(헤더가 없는 배포본의 C API 를 ctypes 로 부르기 전에 무엇이 있는지 보려고).

  python research/gpu/4단계/pe내보내기.py build/llama-b11496/llama.dll [거르기]
"""
import struct
import sys


def 내보내기(path):
    b = open(path, "rb").read()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    assert b[pe:pe + 4] == b"PE\0\0"
    n_sec = struct.unpack_from("<H", b, pe + 6)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", b, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)
    exp_rva, _ = struct.unpack_from("<II", b, dd)
    sec = opt + struct.unpack_from("<H", b, pe + 20)[0]
    secs = [struct.unpack_from("<8sIIII", b, sec + 40 * i) for i in range(n_sec)]

    def off(rva):
        for _, vsize, va, rsize, raw in secs:
            if va <= rva < va + max(vsize, rsize):
                return rva - va + raw
        raise ValueError(hex(rva))
    e = off(exp_rva)
    n_names, names_rva = struct.unpack_from("<I", b, e + 24)[0], struct.unpack_from("<I", b, e + 32)[0]
    out = []
    for i in range(n_names):
        r = struct.unpack_from("<I", b, off(names_rva) + 4 * i)[0]
        o = off(r)
        out.append(b[o:b.index(b"\0", o)].decode())
    return out


if __name__ == "__main__":
    xs = 내보내기(sys.argv[1])
    flt = sys.argv[2] if len(sys.argv) > 2 else ""
    for x in xs:
        if flt in x:
            print(x)
