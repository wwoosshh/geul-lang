#!/usr/bin/env python3
"""cubin 해부 (탐침 S1): NVIDIA GPU 기계어 파일(cubin, ELF)의 섹션·기호·메타데이터(.nv.info)를 풀어 보인다.

  python research/gpu/탐침/큐빈해부.py <파일.cubin> [--바이트]

cubin 형식은 공개 문서가 없다. 여기의 이름표(EIATTR_*)는 공개된 역공학 자료(CuAssembler 등)를 따른 것이고,
값이 기대와 맞는지(매개변수 개수·크기, 레지스터 수, 종료 명령 위치)로 이 파일에서 확인한다.
"""
import io
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EIATTR = {
    0x01: "PAD", 0x02: "IMAGE_SLOT", 0x03: "JUMPTABLE_RELOCS", 0x04: "CTAIDZ_USED", 0x05: "MAX_THREADS",
    0x06: "IMAGE_OFFSET", 0x07: "IMAGE_SIZE", 0x08: "TEXTURE_NORMALIZED", 0x09: "SAMPLER_INIT",
    0x0A: "PARAM_CBANK", 0x0B: "SMEM_PARAM_OFFSETS", 0x0C: "CBANK_PARAM_OFFSETS", 0x0D: "SYNC_STACK",
    0x0E: "TEXID_SAMPID_MAP", 0x0F: "EXTERNS", 0x10: "REQNTID", 0x11: "FRAME_SIZE", 0x12: "MIN_STACK_SIZE",
    0x13: "SAMPLER_FORCE_UNNORMALIZED", 0x14: "BINDLESS_IMAGE_OFFSETS", 0x15: "BINDLESS_TEXTURE_BANK",
    0x16: "BINDLESS_SURFACE_BANK", 0x17: "KPARAM_INFO", 0x18: "SMEM_PARAM_SIZE", 0x19: "CBANK_PARAM_SIZE",
    0x1A: "QUERY_NUMATTRIB", 0x1B: "MAXREG_COUNT", 0x1C: "EXIT_INSTR_OFFSETS", 0x1D: "S2RCTAID_INSTR_OFFSETS",
    0x1E: "CRS_STACK_SIZE", 0x1F: "NEED_CNP_WRAPPER", 0x20: "NEED_CNP_PATCH", 0x21: "EXPLICIT_CACHING",
    0x22: "ISTYPEP_USED", 0x23: "MAX_STACK_SIZE", 0x24: "SUQ_USED", 0x25: "LD_CACHEMOD_INSTR_OFFSETS",
    0x26: "LOAD_CACHE_REQUEST", 0x27: "ATOM_SYS_INSTR_OFFSETS", 0x28: "COOP_GROUP_INSTR_OFFSETS",
    0x29: "COOP_GROUP_MAX_REGIDS", 0x2A: "SW1850030_WAR", 0x2B: "WMMA_USED", 0x2C: "HAS_PRE_V10_OBJECT",
    0x2D: "ATOMF16_EMUL_INSTR_OFFSETS", 0x2E: "ATOM16_EMUL_INSTR_REG_MAP", 0x2F: "REGCOUNT", 0x30: "SW2393858_WAR",
    0x31: "INT_WARP_WIDE_INSTR_OFFSETS", 0x32: "SHARED_SCRATCH", 0x33: "STATISTICS", 0x34: "INDIRECT_BRANCH_TARGETS",
    0x35: "SW2861232_WAR", 0x36: "SW_WAR", 0x37: "CUDA_API_VERSION", 0x38: "NUM_MBARRIERS",
    0x39: "MBARRIER_INSTR_OFFSETS", 0x3A: "COROUTINE_RESUME_ID_OFFSETS", 0x3B: "SAM_REGION_STACK_SIZE",
    0x3C: "PER_REG_TARGET_PERF_STATS", 0x3D: "CTA_PER_CLUSTER", 0x3E: "EXPLICIT_CLUSTER", 0x3F: "MAX_CLUSTER_RANK",
    0x40: "INSTR_REG_MAP",
}
EIFMT = {1: "NVAL", 2: "BVAL", 3: "HVAL", 4: "SVAL"}


NUL = bytes([0])


def cstr(data, off):
    end = data.index(NUL, off)
    return data[off:end].decode()


def parse(b):
    e = {}
    (e["type"], e["machine"], e["version"], e["entry"], e["phoff"], e["shoff"], e["flags"], e["ehsize"],
     e["phentsize"], e["phnum"], e["shentsize"], e["shnum"], e["shstrndx"]) = struct.unpack_from("<HHIQQQIHHHHHH", b, 16)
    secs = []
    for k in range(e["shnum"]):
        f = struct.unpack_from("<IIQQQQIIQQ", b, e["shoff"] + k * e["shentsize"])
        secs.append(dict(zip(("name", "type", "flags", "addr", "off", "size", "link", "info", "align", "entsize"), f)))
    shstr = secs[e["shstrndx"]]
    for s in secs:
        s["nm"] = cstr(b, shstr["off"] + s["name"])
        s["data"] = b[s["off"]:s["off"] + s["size"]] if s["type"] != 8 else b""
    phs = []
    for k in range(e["phnum"]):
        f = struct.unpack_from("<IIQQQQQQ", b, e["phoff"] + k * e["phentsize"])
        phs.append(dict(zip(("type", "flags", "offset", "vaddr", "paddr", "filesz", "memsz", "align"), f)))
    return e, secs, phs


def nv_info(data):
    out = []
    k = 0
    while k < len(data):
        fmt, attr = data[k], data[k + 1]
        if fmt == 4:
            size = struct.unpack_from("<H", data, k + 2)[0]
            val = data[k + 4:k + 4 + size]
            k += 4 + size
        elif fmt == 3:
            val = struct.unpack_from("<H", data, k + 2)[0]
            k += 4
        elif fmt == 2:
            val = data[k + 2]
            k += 4   # BVAL 도 4바이트 단위로 정렬된다고 가정 — 해부 결과로 확인
        else:
            val = None
            k += 4
        out.append((EIFMT.get(fmt, fmt), EIATTR.get(attr, f"0x{attr:02X}"), val))
    return out


def show_val(name, val):
    if isinstance(val, (bytes, bytearray)):
        if name == "KPARAM_INFO" and len(val) == 12:
            index, ordinal_off, info = struct.unpack("<IIi", val)
            ordinal, offset = ordinal_off & 0xFFFF, ordinal_off >> 16
            size = (info >> 18) & 0x3FFF
            return f"색인 {index} 순번 {ordinal} 오프셋 {offset:#x} 크기 {size} (원본 {val.hex()})"
        if name in ("EXIT_INSTR_OFFSETS", "S2RCTAID_INSTR_OFFSETS", "CBANK_PARAM_OFFSETS") and len(val) % 4 == 0:
            return "[" + ", ".join(f"{x:#x}" for x in struct.unpack(f"<{len(val) // 4}I", val)) + "]"
        if len(val) % 4 == 0 and len(val) <= 16:
            return "u32 " + " ".join(str(x) for x in struct.unpack(f"<{len(val) // 4}I", val)) + f"  ({val.hex()})"
        return val.hex()
    return str(val)


def main(argv):
    if not argv:
        print(__doc__)
        return 3
    b = open(argv[0], "rb").read()
    e, secs, phs = parse(b)
    print(f"ELF: 머신 {e['machine']} 형식 {e['type']} 깃발 {e['flags']:#x} (sm_{(e['flags'] >> 8) & 0xFF}) "
          f"OSABI {b[7]} ABI판 {b[8]} | 섹션 {e['shnum']}개, 프로그램 헤더 {e['phnum']}개")
    for k, s in enumerate(secs):
        extra = ""
        if s["nm"].startswith(".text."):
            extra = f"  ← 레지스터 {s['info'] >> 24}, 기호 {s['info'] & 0xFFFFFF}"
        print(f"[{k:2}] {s['nm']:<26} 형식 {s['type']:#x} 깃발 {s['flags']:#x} 크기 {s['size']:>4} 연결 {s['link']} 정보 {s['info']:#x} 정렬 {s['align']}{extra}")
    strtab = next(s for s in secs if s["nm"] == ".strtab")
    symtab = next(s for s in secs if s["nm"] == ".symtab")
    print("기호:")
    for k in range(symtab["size"] // 24):
        name, info, other, shndx, value, size = struct.unpack_from("<IBBHQQ", symtab["data"], k * 24)
        print(f"  {k}: {cstr(strtab['data'], name):<30} 정보 {info:#x} 기타 {other:#x} 섹션 {shndx} 값 {value} 크기 {size}")
    for s in secs:
        if s["nm"].startswith(".nv.info"):
            print(f"{s['nm']}:")
            for fmt, name, val in nv_info(s["data"]):
                print(f"  {fmt:<4} {name:<24} {show_val(name, val)}")
    for s in secs:
        if s["nm"].startswith(".nv.constant0"):
            nz = [(i, s["data"][i]) for i in range(len(s["data"])) if s["data"][i]]
            print(f"{s['nm']}: {s['size']} 바이트, 0 이 아닌 바이트 {len(nz)}개")
    for k, p in enumerate(phs):
        print(f"PH{k}: 형식 {p['type']:#x} 깃발 {p['flags']:#x} 오프셋 {p['offset']} 파일크기 {p['filesz']} 메모리크기 {p['memsz']} 정렬 {p['align']}")
    if "--바이트" in argv:
        for s in secs:
            if s["nm"].startswith(".text."):
                code = s["data"]
                print(f"{s['nm']} ({len(code) // 16} 명령, 명령당 16바이트):")
                for i in range(0, len(code), 16):
                    print(f"  {i:#06x}: {code[i:i + 8][::-1].hex()} {code[i + 8:i + 16][::-1].hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
