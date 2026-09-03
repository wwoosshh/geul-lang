"""PE32+ 기록기. 섹션: .text .rdata(문자열+임포트) .data. 재배치 없음(고정 베이스), RIP 상대 주소만 사용."""
import struct
import time

IMAGE_BASE = 0x140000000
SECTION_ALIGN = 0x1000
FILE_ALIGN = 0x200


def align(n, a):
    return (n + a - 1) // a * a


def write_pe(img, path):
    # ----- .rdata 배치: 문자열, 임포트 디렉터리 -----
    rdata = bytearray()
    str_offsets = []
    for s in img.strings:
        str_offsets.append(len(rdata))
        rdata += s
    rdata += b"\0" * (align(len(rdata), 16) - len(rdata))
    dlls = list(img.imports.items())
    # 이름 테이블 (hint/name)
    name_off = {}
    names_blob = bytearray()
    for dll, names in dlls:
        for n in names:
            name_off[(dll, n)] = len(names_blob)
            names_blob += b"\0\0" + n.encode("ascii") + b"\0"
            if len(names_blob) % 2:
                names_blob += b"\0"
    dllname_off = {}
    for dll, _ in dlls:
        dllname_off[dll] = len(names_blob)
        names_blob += dll.encode("ascii") + b"\0"
    desc_off = len(rdata)
    desc_size = 20 * (len(dlls) + 1)
    thunks_off = desc_off + desc_size
    thunks_off = align(thunks_off, 8)
    # ILT 와 IAT: dll 별 (n+1)*8
    ilt_off = {}
    iat_off = {}
    cur = thunks_off
    for dll, names in dlls:
        ilt_off[dll] = cur
        cur += 8 * (len(names) + 1)
    iat_start = cur
    for dll, names in dlls:
        iat_off[dll] = cur
        cur += 8 * (len(names) + 1)
    iat_end = cur
    names_off = cur
    rdata_total = names_off + len(names_blob)
    text_rva = SECTION_ALIGN
    text_size = len(img.code)
    rdata_rva = align(text_rva + text_size, SECTION_ALIGN)
    data_rva = align(rdata_rva + rdata_total, SECTION_ALIGN)
    # rdata 본문 조립
    rdata += b"\0" * (desc_off - len(rdata))
    for dll, names in dlls:
        rdata += struct.pack("<IIIII", rdata_rva + ilt_off[dll], 0, 0, rdata_rva + names_off + dllname_off[dll], rdata_rva + iat_off[dll])
    rdata += b"\0" * 20
    rdata += b"\0" * (thunks_off - len(rdata))
    for table in (ilt_off, iat_off):
        for dll, names in dlls:
            assert len(rdata) == table[dll]
            for n in names:
                rdata += struct.pack("<Q", rdata_rva + names_off + name_off[(dll, n)])
            rdata += b"\0" * 8
    rdata += names_blob
    iat_entry_rva = {}
    for dll, names in dlls:
        for k, n in enumerate(names):
            iat_entry_rva[n] = rdata_rva + iat_off[dll] + 8 * k
    # ----- 코드 fixup -----
    code = bytearray(img.code)
    for off, kind, target in img.code_fixups:
        at = text_rva + off + 4
        if kind == "iat":
            tgt = iat_entry_rva[target]
        elif kind == "str":
            tgt = rdata_rva + str_offsets[target]
        elif kind == "data":
            tgt = data_rva + img.data_globals[target]
        else:
            raise KeyError(kind)
        code[off:off + 4] = struct.pack("<i", tgt - at)
    # ----- 데이터 절대 주소 fixup -----
    data = bytearray(img.data)
    for off, kind, target in img.data_abs_fixups:
        if kind == "str":
            va = IMAGE_BASE + rdata_rva + str_offsets[target]
        elif kind == "data":
            va = IMAGE_BASE + data_rva + img.data_globals[target]
        else:
            raise KeyError(kind)
        data[off:off + 8] = struct.pack("<Q", va)
    if not data:
        data = bytearray(b"\0" * 16)
    # ----- 헤더 -----
    sections = [
        (b".text", text_rva, code, 0x60000020),
        (b".rdata", rdata_rva, bytes(rdata), 0x40000040),
        (b".data", data_rva, bytes(data), 0xC0000040),
    ]
    headers_size = 0x400
    raw = headers_size
    sec_headers = []
    file_parts = []
    for name, rva, body, flags in sections:
        raw_size = align(len(body), FILE_ALIGN)
        sec_headers.append(struct.pack("<8sIIIIIIHHI", name.ljust(8, b"\0"), len(body), rva, raw_size, raw, 0, 0, 0, 0, flags))
        file_parts.append((raw, body + b"\0" * (raw_size - len(body))))
        raw += raw_size
    size_of_image = align(data_rva + len(data), SECTION_ALIGN)
    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    dos[0x3C:0x40] = struct.pack("<I", 0x40)
    coff = struct.pack("<HHIIIHH", 0x8664, len(sections), int(time.time()) & 0xFFFFFFFF, 0, 0, 240, 0x0022 | 0x0001)
    entry_rva = text_rva + img.entry
    opt = struct.pack(
        "<HBBIIIIIQIIHHHHHHIIIIHHQQQQII",
        0x20B, 14, 0, len(code), len(rdata), len(data), entry_rva, text_rva,
        IMAGE_BASE, SECTION_ALIGN, FILE_ALIGN, 6, 0, 0, 0, 6, 0, 0,
        size_of_image, headers_size, 0, 3, 0x8100,
        0x100000, 0x1000, 0x100000, 0x1000, 0, 16,
    )
    dirs = [(0, 0)] * 16
    dirs[1] = (rdata_rva + desc_off, desc_size)              # 임포트 디렉터리
    dirs[12] = (rdata_rva + iat_start, iat_end - iat_start)  # IAT
    opt += b"".join(struct.pack("<II", a, b) for a, b in dirs)
    header = bytes(dos) + b"PE\0\0" + coff + opt + b"".join(sec_headers)
    assert len(header) <= headers_size
    out = bytearray(header + b"\0" * (headers_size - len(header)))
    for off, body in file_parts:
        assert len(out) == off
        out += body
    with open(path, "wb") as fp:
        fp.write(out)
