"""ptxas 가 64 비트 나눗셈 · 나머지를 어떻게 바꾸는가 — 커널 하나씩 따로 cubin 으로 링크해 부르는 하위 함수(__cuda_sm20_*)가 있는지 본다."""
import sys, ctypes, re
sys.stdout.reconfigure(encoding="utf-8")
cu = ctypes.WinDLL("nvcuda.dll")


def ok(r):
    assert r == 0, r


ok(cu.cuInit(0))
dev = ctypes.c_int(); ok(cu.cuDeviceGet(ctypes.byref(dev), 0))
ctx = ctypes.c_void_p(); ok(cu.cuCtxCreate_v2(ctypes.byref(ctx), 0, dev))
body = {
    "reg64": "mov.b64 %rd3, 64; div.s64 %rd2, %rd1, %rd3;",
    "imm64": "div.s64 %rd2, %rd1, 64;",
    "u64imm64": "div.u64 %rd2, %rd1, 64;",
    "imm768": "div.s64 %rd2, %rd1, 768;",
    "u64imm768": "div.u64 %rd2, %rd1, 768;",
    "remimm32": "rem.s64 %rd2, %rd1, 32;",
    "u32reg32": "cvt.u32.u64 %r1, %rd1; mov.b32 %r3, 32; div.u32 %r2, %r1, %r3; cvt.u64.u32 %rd2, %r2;",
    "u32reg768": "cvt.u32.u64 %r1, %rd1; mov.b32 %r3, 768; div.u32 %r2, %r1, %r3; cvt.u64.u32 %rd2, %r2;",
    "none": "mov.b64 %rd2, %rd1;",
}
for k, b in body.items():
    p = (".version 7.4\n.target sm_80\n.address_size 64\n" + f""".visible .entry k_{k}(.param .u64 p, .param .u64 x) {{
 .reg .b64 %rd<8>; .reg .b32 %r<8>;
 ld.param.u64 %rd5, [p]; ld.param.u64 %rd1, [x];
 {b}
 st.global.u64 [%rd5], %rd2;
 ret;
}}
""").encode() + b"\0"
    st = ctypes.c_void_p()
    ok(cu.cuLinkCreate_v2(0, None, None, ctypes.byref(st)))
    ok(cu.cuLinkAddData_v2(st, 1, ctypes.c_char_p(p), len(p), b"t.ptx", 0, None, None))
    cub, n = ctypes.c_void_p(), ctypes.c_size_t()
    ok(cu.cuLinkComplete(st, ctypes.byref(cub), ctypes.byref(n)))
    data = ctypes.string_at(cub, n.value)
    subs = sorted(set(m.decode() for m in re.findall(rb"__cuda_sm20_\w+", data)))
    print(f"{k:12s} cubin {n.value:6d} 바이트, 부름: {subs}")
    cu.cuLinkDestroy(st)
