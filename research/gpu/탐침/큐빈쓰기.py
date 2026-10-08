#!/usr/bin/env python3
"""cubin 작성기 (탐침 S1, 참조판): SASS 바이트와 커널의 사실들로 NVIDIA GPU 기계어 파일(cubin, ELF64)을 처음부터 쓴다.

  python research/gpu/탐침/큐빈쓰기.py <드라이버.cubin> <출력.cubin> [--프로그램헤더] [--전역정보] [--노트기호없음] [--가상89]

S1 에서는 SASS 명령 바이트와 코드에서 나오는 사실(레지스터 수, 스택 크기, 종료 명령 위치)을 드라이버가 만든 cubin 에서
가져오고, 그것을 담는 포장 — ELF 머리, 섹션, 문자열표, 기호표, 매개변수 메타데이터, 상수 영역, 프로그램 헤더 — 은 여기서 쓴다.
S2 부터는 SASS 와 그 사실들도 글이 낸다. 글로 쓴 작성기(큐빈.gl)가 이 파일과 바이트가 같아야 한다.
"""
import importlib.util
import io
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("haebu", os.path.join(HERE, "큐빈해부.py"))
haebu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(haebu)

# ELF 와 NVIDIA 상수 — 드라이버 cubin 에서 읽은 값 (sm_89, CUDA 13.4 드라이버)
EM_CUDA = 190
ELFOSABI_CUDA = 0x41
ABI_VERSION = 8
E_FLAGS_SM89 = 0x06005904
SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB, SHT_NOTE = 1, 2, 3, 7
SHF_NOTE_CUINFO, SHF_NOTE_TKINFO = 0x1000000, 0x2000000   # NVIDIA 노트의 섹션 깃발
SHT_CUDA_INFO = 0x70000000
SHF_ALLOC, SHF_EXECINSTR, SHF_INFO_LINK = 0x2, 0x4, 0x40
PARAM_BASE = 0x160            # 상수 영역 0 에서 매개변수가 시작하는 자리 (그 앞은 드라이버 몫)
EIATTR_FRAME_SIZE, EIATTR_REGCOUNT, EIATTR_MIN_STACK_SIZE = 0x11, 0x2F, 0x12
EIATTR_EXIT_INSTR_OFFSETS, EIATTR_MAXREG_COUNT, EIATTR_KPARAM_INFO = 0x1C, 0x1B, 0x17
EIATTR_CBANK_PARAM_SIZE, EIATTR_PARAM_CBANK, EIATTR_CUDA_API_VERSION = 0x19, 0x0A, 0x37


def sval(attr, payload):
    return struct.pack("<BBH", 4, attr, len(payload)) + payload


def hval(attr, value):
    return struct.pack("<BBH", 3, attr, value)


def note(typ, desc):
    name = b"NVIDIA Corp" + bytes(1)
    pad = lambda x: x + bytes((-len(x)) % 4)
    return struct.pack("<III", len(name), len(desc), typ) + pad(name) + pad(desc)


def tkinfo(strings):
    """도구 정보 노트(형식 2000): 판 2, 문자열 다섯의 위치, 문자열들.
    드라이버의 것: 목적 파일 이름, 도구 이름, 도구 판, 빌드 문자열, 명령줄 옵션."""
    blob = b"".join(x.encode() + bytes(1) for x in strings)
    offs, o = [], 0
    for x in strings:
        offs.append(o)
        o += len(x.encode()) + 1
    return note(2000, struct.pack("<6I", 2, *offs) + blob)


def cuinfo(virtual_sm, api):
    """CUDA 정보 노트(형식 1000): (2, 가상 SM, API 판)."""
    return note(1000, struct.pack("<HHI", 2, virtual_sm, api))


GEUL_TOOL = ["geul-gpu-probe", "geulc", "geul 1.2.1 research/gpu S1", "research/gpu", ""]


def facts_from_driver(path):
    """S1: 드라이버 cubin 에서 코드와 코드의 사실을 가져온다."""
    b = open(path, "rb").read()
    e, secs, _ = haebu.parse(b)
    text = next(s for s in secs if s["nm"].startswith(".text."))
    name = text["nm"][len(".text."):]
    info = next(s for s in secs if s["nm"] == ".nv.info." + name)
    glob = next(s for s in secs if s["nm"] == ".nv.info")
    f = {"name": name, "sass": text["data"], "regs": text["info"] >> 24, "params": [], "exits": [], "extra": []}
    for fmt, attr, val in haebu.nv_info(glob["data"]):
        if attr == "FRAME_SIZE":
            f["frame"] = struct.unpack("<II", val)[1]
        if attr == "MIN_STACK_SIZE":
            f["min_stack"] = struct.unpack("<II", val)[1]
    for fmt, attr, val in haebu.nv_info(info["data"]):
        if attr == "EXIT_INSTR_OFFSETS":
            f["exits"] = list(struct.unpack(f"<{len(val) // 4}I", val))
        elif attr == "KPARAM_INFO":
            f["params"].append((struct.unpack("<IIi", val)[2] >> 18) & 0x3FFF)
        elif attr == "CUDA_API_VERSION":
            f["api"] = struct.unpack("<I", val)[0]
    return f


def build(f, tool=None, virtual_sm=52, phdrs=False, global_info=False, note_symbols=True):
    """cubin 바이트를 처음부터 쓴다 (S1 에서 찾은 최소 구성).

    섹션: .shstrtab .strtab .symtab .note.nv.tkinfo .note.nv.cuinfo [.nv.info] .nv.info.<커널> .nv.constant0.<커널> .text.<커널>
    드라이버 실험: 노트 둘은 이름으로 찾는 듯 반드시 있어야 하고(cuinfo 는 tkinfo 를 가리킨다),
    전역 .nv.info·프로그램 헤더·디버그 정보·호출 그래프는 없어도 받는다."""
    name = f["name"]
    nparam = len(f["params"])
    offsets = []
    off = 0
    for size in f["params"]:
        off = (off + size - 1) // size * size
        offsets.append(off)
        off += size
    param_bytes = off
    T, C, K = ".text." + name, ".nv.constant0." + name, ".nv.info." + name
    sec_names = [".shstrtab", ".strtab", ".symtab", ".note.nv.tkinfo", ".note.nv.cuinfo"]
    if global_info:
        sec_names.append(".nv.info")
    sec_names += [K, C, T]
    idx = {n: k + 1 for k, n in enumerate(sec_names)}          # 0 번은 빈 섹션

    # 기호: 0 없음, (노트 섹션 기호 둘), .text 섹션, .nv.constant0 섹션, 커널(전역 함수)
    sym_sections = ([".note.nv.tkinfo", ".note.nv.cuinfo"] if note_symbols else []) + [T, C]
    strtab = bytes(1)
    str_off = {}
    for n in sym_sections + [name]:
        str_off[n] = len(strtab)
        strtab += n.encode() + bytes(1)
    symtab = struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0)
    sym_index = {}
    for n in sym_sections:
        sym_index[n] = len(symtab) // 24
        symtab += struct.pack("<IBBHQQ", str_off[n], 0x03, 0, idx[n], 0, 0)
    SYM_KERNEL = len(symtab) // 24
    symtab += struct.pack("<IBBHQQ", str_off[name], 0x12, 0x10, idx[T], 0, len(f["sass"]))

    shstrtab = bytes(1)
    shname = {}
    for n in sec_names:
        shname[n] = len(shstrtab)
        shstrtab += n.encode() + bytes(1)

    nv_info = (sval(EIATTR_FRAME_SIZE, struct.pack("<II", SYM_KERNEL, f.get("frame", 0)))
               + sval(EIATTR_REGCOUNT, struct.pack("<II", SYM_KERNEL, f["regs"]))
               + sval(EIATTR_MIN_STACK_SIZE, struct.pack("<II", SYM_KERNEL, f.get("min_stack", 0))))
    # 드라이버가 적는 순서 그대로. 0x5F 와 0x66 은 이름을 모른다 — 드라이버가 이 커널들에 늘 넣는 값(0, 3)을 따른다.
    kinfo = sval(EIATTR_EXIT_INSTR_OFFSETS, struct.pack(f"<{len(f['exits'])}I", *f["exits"]))
    kinfo += hval(0x5F, 0)
    kinfo += hval(EIATTR_MAXREG_COUNT, 255)
    for k in range(nparam):
        kinfo += sval(EIATTR_KPARAM_INFO, struct.pack("<IIi", 0, k | (offsets[k] << 16), 0x1F000 | (f["params"][k] << 18)))
    kinfo += hval(EIATTR_CBANK_PARAM_SIZE, param_bytes)
    kinfo += sval(EIATTR_PARAM_CBANK, struct.pack("<IHH", sym_index[C], PARAM_BASE, param_bytes))
    kinfo += sval(EIATTR_CUDA_API_VERSION, struct.pack("<I", f.get("api", 134)))
    kinfo += sval(0x66, struct.pack("<I", 3))

    datas = {".shstrtab": shstrtab, ".strtab": strtab, ".symtab": symtab,
             ".note.nv.tkinfo": tkinfo(tool or GEUL_TOOL), ".note.nv.cuinfo": cuinfo(virtual_sm, f.get("api", 134)),
             ".nv.info": nv_info, K: kinfo, C: bytes(PARAM_BASE + param_bytes), T: f["sass"]}
    heads = {   # 형식, 깃발, 연결, 정보, 정렬, 항목크기
        ".shstrtab": (SHT_STRTAB, 0, 0, 0, 1, 0),
        ".strtab": (SHT_STRTAB, 0, 0, 0, 1, 0),
        ".symtab": (SHT_SYMTAB, 0, idx[".strtab"], SYM_KERNEL, 8, 24),
        ".note.nv.tkinfo": (SHT_NOTE, SHF_NOTE_TKINFO, 0, 0, 4, 0),
        ".note.nv.cuinfo": (SHT_NOTE, SHF_NOTE_CUINFO, idx[".note.nv.tkinfo"], 0, 4, 0),
        ".nv.info": (SHT_CUDA_INFO, 0, idx[".symtab"], 0, 4, 0),
        K: (SHT_CUDA_INFO, SHF_INFO_LINK, idx[".symtab"], idx[T], 4, 0),
        C: (SHT_PROGBITS, SHF_ALLOC | SHF_INFO_LINK, 0, idx[T], 4, 0),
        T: (SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR, idx[".symtab"], (f["regs"] << 24) | SYM_KERNEL, 128, 0),
    }
    out = bytearray(64)
    placed = {}
    for n in sec_names:
        while len(out) % heads[n][4]:
            out.append(0)
        placed[n] = len(out)
        out += datas[n]
    while len(out) % 8:
        out.append(0)
    shoff = len(out)
    out += bytes(64)                                    # 0 번 빈 섹션
    for n in sec_names:
        typ, flags, link, info, align, entsize = heads[n]
        out += struct.pack("<IIQQQQIIQQ", shname[n], typ, flags, 0, placed[n], len(datas[n]), link, info, align, entsize)
    phoff, phnum = 0, 0
    if phdrs:
        phoff, phnum = len(out), 3
        ph = 56 * phnum
        lo = placed[C]
        ls = placed[T] + len(f["sass"]) - lo
        out += struct.pack("<IIQQQQQQ", 6, 5, phoff, 0, 0, ph, ph, 8)
        out += struct.pack("<IIQQQQQQ", 1, 5, lo, 0, 0, ls, ls, 8)
        out += struct.pack("<IIQQQQQQ", 1, 5, phoff, 0, 0, ph, ph, 8)
    ident = bytes([0x7F]) + b"ELF" + bytes([2, 1, 1, ELFOSABI_CUDA, ABI_VERSION]) + bytes(7)
    out[0:64] = ident + struct.pack("<HHIQQQIHHHHHH", 2, EM_CUDA, 1, 0, phoff, shoff, E_FLAGS_SM89,
                                    64, 56, phnum, 64, len(sec_names) + 1, idx[".shstrtab"])
    return bytes(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 3
    f = facts_from_driver(argv[0])
    data = build(f, phdrs="--프로그램헤더" in argv, global_info="--전역정보" in argv,
                 note_symbols="--노트기호없음" not in argv, virtual_sm=89 if "--가상89" in argv else 52)
    open(argv[1], "wb").write(data)
    print(f"cubin {len(data)} 바이트: 커널 {f['name']}, SASS {len(f['sass'])} 바이트, 레지스터 {f['regs']}, "
          f"매개변수 {f['params']}, 종료 {[hex(x) for x in f['exits']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
