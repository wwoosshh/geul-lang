"""ELF64 기록기 — 리눅스 x86-64 대상 (D-50). 고정 베이스의 실행 파일(ET_EXEC, 0x400000)이고, 동적 링크로 바깥 함수를 가져온다.

- 가져오는 이름마다 GOT 칸 하나. 실행 전에 ld.so 가 R_X86_64_GLOB_DAT 로 채운다(DF_BIND_NOW).
- 코드는 PE 와 같은 [rip+disp32] · rel32 만 쓴다. 고정 베이스라서 .data 의 절대 주소도 재배치 없이 이 파일 안에서 정해진다.
- 세그먼트 셋: R(ELF 머리 · 프로그램 머리 · interp · 동적 표 · 문자열), RX(.text), RW(.dynamic · GOT · .data).
  세그먼트는 파일에서도 페이지에 맞춰 둔다(파일 위치 ≡ 가상 주소, 4 KB 마다).
- 섹션 머리는 내지 않는다(실행에는 필요 없다). 같은 입력은 같은 바이트(시각 · 무작위 없음).
"""
import struct

BASE = 0x400000
PAGE = 0x1000
INTERP = b"/lib64/ld-linux-x86-64.so.2\0"
PT_LOAD, PT_DYNAMIC, PT_INTERP, PT_PHDR, PT_GNU_STACK = 1, 2, 3, 6, 0x6474E551
DT_NULL, DT_NEEDED, DT_HASH, DT_STRTAB, DT_SYMTAB, DT_RELA, DT_RELASZ, DT_RELAENT = 0, 1, 4, 5, 6, 7, 8, 9
DT_STRSZ, DT_SYMENT, DT_DEBUG, DT_FLAGS = 10, 11, 21, 30
DF_BIND_NOW = 8
R_X86_64_GLOB_DAT = 6
NPH = 7


def align(n, a):
    return (n + a - 1) // a * a


def write_elf(img, path):
    libs = list(img.imports.keys())
    names = [n for lib in libs for n in img.imports[lib]]
    # ----- .dynstr · .dynsym · .hash -----
    dynstr = bytearray(b"\0")
    lib_off = {}
    for lib in libs:
        lib_off[lib] = len(dynstr)
        dynstr += lib.encode("ascii") + b"\0"
    name_off = {}
    for n in names:
        name_off[n] = len(dynstr)
        dynstr += n.encode("ascii") + b"\0"
    nsym = 1 + len(names)
    dynsym = bytearray(24)                       # 0 번은 빈 기호
    for n in names:
        dynsym += struct.pack("<IBBHQQ", name_off[n], 0x12, 0, 0, 0, 0)    # STB_GLOBAL · STT_FUNC, 정의 없음
    hash_tab = struct.pack("<II", 1, nsym) + struct.pack("<I", 0) + b"\0" * (4 * nsym)    # 통 하나 — 내놓는 기호가 없다
    # ----- R 세그먼트의 배치 -----
    off = 64 + 56 * NPH
    off_interp = off
    off += len(INTERP)
    off_dynstr = off
    off += len(dynstr)
    off_dynsym = align(off, 8)
    off = off_dynsym + len(dynsym)
    off_hash = align(off, 8)
    off = off_hash + len(hash_tab)
    off_rela = align(off, 8)
    off = off_rela + 24 * len(names)
    off_rodata = align(off, 16)
    str_offsets = []
    rodata = bytearray()
    for s in img.strings:
        str_offsets.append(len(rodata))
        rodata += s
    r_end = off_rodata + len(rodata)
    text_off = align(r_end, PAGE)
    text_va = BASE + text_off
    rw_off = align(text_off + len(img.code), PAGE)
    rw_va = BASE + rw_off
    # ----- RW 세그먼트: .dynamic · GOT · .data -----
    ndyn = len(libs) + 11
    dyn_size = 16 * ndyn
    got_off = dyn_size
    data_off = align(got_off + 8 * len(names), 16)
    got_va = {n: rw_va + got_off + 8 * k for k, n in enumerate(names)}
    data_va = rw_va + data_off
    rodata_va = BASE + off_rodata
    # ----- 코드 고정 -----
    code = bytearray(img.code)
    for at, kind, target in img.code_fixups:
        nxt = text_va + at + 4
        if kind == "iat":
            tgt = got_va[target]
        elif kind == "str":
            tgt = rodata_va + str_offsets[target]
        elif kind == "data":
            tgt = data_va + img.data_globals[target]
        elif kind == "ftab":
            tgt = data_va + img.func_table[target]
        else:
            raise KeyError(kind)
        code[at:at + 4] = struct.pack("<i", tgt - nxt)
    # ----- 데이터 절대 주소 고정 -----
    data = bytearray(img.data)
    for at, kind, target in img.data_abs_fixups:
        if kind == "str":
            va = rodata_va + str_offsets[target]
        elif kind == "data":
            va = data_va + img.data_globals[target]
        elif kind == "faddr":
            va = text_va + img.func_offsets[target]
        else:
            raise KeyError(kind)
        data[at:at + 8] = struct.pack("<Q", va)
    if not data:
        data = bytearray(b"\0" * 16)
    # ----- .dynamic -----
    dyn = bytearray()
    for lib in libs:
        dyn += struct.pack("<qQ", DT_NEEDED, lib_off[lib])
    for tag, val in ((DT_HASH, BASE + off_hash), (DT_STRTAB, BASE + off_dynstr), (DT_SYMTAB, BASE + off_dynsym),
                     (DT_STRSZ, len(dynstr)), (DT_SYMENT, 24), (DT_RELA, BASE + off_rela), (DT_RELASZ, 24 * len(names)),
                     (DT_RELAENT, 24), (DT_FLAGS, DF_BIND_NOW), (DT_DEBUG, 0), (DT_NULL, 0)):
        dyn += struct.pack("<qQ", tag, val)
    assert len(dyn) == dyn_size
    rw = bytearray(dyn)
    rw += b"\0" * (data_off - len(rw))
    rw += data
    # ----- 재배치 -----
    rela = bytearray()
    for k, n in enumerate(names):
        rela += struct.pack("<QQq", got_va[n], ((k + 1) << 32) | R_X86_64_GLOB_DAT, 0)
    # ----- 프로그램 머리 -----
    ph = bytearray()
    ph += struct.pack("<IIQQQQQQ", PT_PHDR, 4, 64, BASE + 64, BASE + 64, 56 * NPH, 56 * NPH, 8)
    ph += struct.pack("<IIQQQQQQ", PT_INTERP, 4, off_interp, BASE + off_interp, BASE + off_interp, len(INTERP), len(INTERP), 1)
    ph += struct.pack("<IIQQQQQQ", PT_LOAD, 4, 0, BASE, BASE, r_end, r_end, PAGE)
    ph += struct.pack("<IIQQQQQQ", PT_LOAD, 5, text_off, text_va, text_va, len(code), len(code), PAGE)
    ph += struct.pack("<IIQQQQQQ", PT_LOAD, 6, rw_off, rw_va, rw_va, len(rw), len(rw), PAGE)
    ph += struct.pack("<IIQQQQQQ", PT_DYNAMIC, 6, rw_off, rw_va, rw_va, dyn_size, dyn_size, 8)
    ph += struct.pack("<IIQQQQQQ", PT_GNU_STACK, 6, 0, 0, 0, 0, 0, 16)
    eh = bytearray(b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8)
    eh += struct.pack("<HHIQQQIHHHHHH", 2, 62, 1, text_va + img.entry, 64, 0, 0, 64, 56, NPH, 64, 0, 0)
    # ----- 파일 -----
    out = bytearray(eh + ph)
    out += b"\0" * (off_interp - len(out)) + INTERP
    out += b"\0" * (off_dynstr - len(out)) + dynstr
    out += b"\0" * (off_dynsym - len(out)) + dynsym
    out += b"\0" * (off_hash - len(out)) + hash_tab
    out += b"\0" * (off_rela - len(out)) + rela
    out += b"\0" * (off_rodata - len(out)) + rodata
    out += b"\0" * (text_off - len(out)) + code
    out += b"\0" * (rw_off - len(out)) + rw
    with open(path, "wb") as fp:
        fp.write(out)
