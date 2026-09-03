#!/usr/bin/env python3
"""글 2세대 단일 빌드 진입점 (D-08).

  python build.py test [필터] [--self]  spec-tests 실행 (컴파일 실패 = 실패, 건너뜀 없음; --self: 글로 쓴 컴파일러 build/self_컴파일러.exe 로)
  python build.py check <파일.gl>  문법·의미 검사
  python build.py selfhost [단계]  자체호스팅 단계별 교차 검증 (단계: 토큰덤프 구문덤프 IR덤프 컴파일러 — 마지막은 exe 바이트 비교 + 고정점)
"""
import os
import sys
import io
import glob
import shutil
import subprocess
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.abspath(__file__))
GEULC = os.path.join(ROOT, "ref", "geulc.py")
TESTS = os.path.join(ROOT, "spec-tests")
COMPILER = [sys.executable, GEULC]        # --self 면 글로 쓴 컴파일러
COMPILER_ENV = dict(os.environ, GEUL_ROOT=ROOT)


def read(path, default=""):
    return open(path, encoding="utf-8").read() if os.path.exists(path) else default


def run_test(test_dir, verbose):
    name = os.path.relpath(test_dir, TESTS).replace("\\", "/")
    main = os.path.join(test_dir, "main.gl")
    errors_file = os.path.join(test_dir, "expect.errors")
    tmp = tempfile.mkdtemp(prefix="geul-")
    try:
        exe = os.path.join(tmp, "main.exe")
        t0 = time.time()
        try:
            r = subprocess.run(COMPILER + [main, "-o", exe], capture_output=True, timeout=60, stdin=subprocess.DEVNULL, env=COMPILER_ENV)
            cout = (r.stdout + r.stderr).decode("utf-8", "replace")
            crc = r.returncode
        except subprocess.TimeoutExpired:
            return name, False, "컴파일 60초 초과"
        dt = time.time() - t0
        if os.path.exists(errors_file):
            wanted = [l for l in read(errors_file).splitlines() if l.strip()]
            if crc == 0 or os.path.exists(exe):
                return name, False, f"오류가 나야 하는데 컴파일됨 (rc={crc})"
            if crc != 1:
                return name, False, f"종료코드 1이어야 하는데 {crc}\n{cout.strip()}"
            missing = [w for w in wanted if w not in cout]
            if missing:
                return name, False, f"오류 메시지에 {missing} 없음:\n{cout.strip()}"
            return name, True, f"{dt:.1f}s"
        if crc != 0 or not os.path.exists(exe):
            return name, False, f"컴파일 실패 (rc={crc}):\n{cout.strip()[-800:]}"
        args = [l for l in read(os.path.join(test_dir, "args.txt")).splitlines() if l != ""]
        stdin_path = os.path.join(test_dir, "stdin.txt")
        stdin_data = open(stdin_path, "rb").read() if os.path.exists(stdin_path) else b""
        try:
            rr = subprocess.run([exe] + args, capture_output=True, timeout=10, input=stdin_data, cwd=tmp)
        except subprocess.TimeoutExpired:
            return name, False, "실행 10초 초과"
        got = rr.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        want = read(os.path.join(test_dir, "expect.stdout"))
        want_code = int(read(os.path.join(test_dir, "expect.code"), "0").strip() or 0)
        code = rr.returncode & 0xFFFFFFFF
        if code >= 0x80000000:
            return name, False, f"실행 크래시 {code:#x}"
        problems = []
        if got != want:
            problems.append(f"출력 불일치\n--- 기대\n{want}--- 실제\n{got}")
        if code != want_code:
            problems.append(f"종료코드 {code} (기대 {want_code})")
        if problems:
            return name, False, "\n".join(problems)
        return name, True, f"{dt:.1f}s"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_test(args):
    global COMPILER
    verbose = "-v" in args
    if "--self" in args:
        self_exe = os.path.join(ROOT, "build", "self_컴파일러.exe")
        if not os.path.exists(self_exe):
            print("build/self_컴파일러.exe 가 없습니다 — 먼저 python build.py selfhost 컴파일러")
            return 3
        COMPILER = [self_exe]
        print(f"컴파일러: {os.path.relpath(self_exe, ROOT)} (글로 쓴 컴파일러)")
    filters = [a for a in args if not a.startswith("-")]
    dirs = sorted(d for d in glob.glob(os.path.join(TESTS, "*", "*")) if os.path.isfile(os.path.join(d, "main.gl")))
    if filters:
        dirs = [d for d in dirs if any(f in d for f in filters)]
    passed = failed = 0
    for d in dirs:
        name, ok, info = run_test(d, verbose)
        if ok:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name}")
            for line in info.splitlines():
                print(f"        {line}")
    print(f"\n결과: PASS={passed} FAIL={failed} (총 {passed + failed})")
    return 0 if failed == 0 else 1


def cmd_check(args):
    if not args:
        print("사용법: build.py check <파일.gl>")
        return 3
    return subprocess.call([sys.executable, GEULC, "--check", args[0]])


def selfhost_inputs(negative=False):
    """negative=True 면 부정 테스트(expect.errors)만: 자체 구현이 같은 종료 코드로 끝나고 기대 메시지를 내는지 본다."""
    if negative:
        return sorted(d for d in glob.glob(os.path.join(TESTS, "*", "*", "main.gl"))
                      if os.path.exists(os.path.join(os.path.dirname(d), "expect.errors")))
    files = sorted(d for d in glob.glob(os.path.join(TESTS, "*", "*", "main.gl"))
                   if not os.path.exists(os.path.join(os.path.dirname(d), "expect.errors")))
    files += sorted(glob.glob(os.path.join(ROOT, "표준", "*.gl")))
    files += sorted(glob.glob(os.path.join(ROOT, "self", "*.gl")))
    return files


def pe_imports(path):
    """PE32+ 임포트 디렉터리에서 DLL 이름 목록."""
    import struct
    b = open(path, "rb").read()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    nsec = struct.unpack_from("<H", b, pe + 6)[0]
    opt = pe + 24
    imp_rva, imp_size = struct.unpack_from("<II", b, opt + 112 + 8 * 1)
    secs = []
    for k in range(nsec):
        off = opt + 240 + 40 * k
        vsize, va, rsize, raw = struct.unpack_from("<IIII", b, off + 8)
        secs.append((va, max(vsize, rsize), raw))
    def rva2off(rva):
        for va, size, raw in secs:
            if va <= rva < va + size:
                return raw + (rva - va)
        raise ValueError(rva)
    out = []
    d = rva2off(imp_rva)
    while True:
        ilt, _, _, name_rva, iat = struct.unpack_from("<IIIII", b, d)
        if name_rva == 0:
            break
        o = rva2off(name_rva)
        out.append(b[o:b.index(b"\0", o)].decode("ascii"))
        d += 20
    return sorted(out)


def selfhost_exe_stage(exe, build_dir):
    """4단계: 긍정 테스트마다 참조 컴파일러와 글로 쓴 컴파일러로 exe 를 만들어 바이트를 비교한다."""
    failed = 0
    n = 0
    inputs = sorted(d for d in glob.glob(os.path.join(TESTS, "*", "*", "main.gl"))
                    if not os.path.exists(os.path.join(os.path.dirname(d), "expect.errors")))
    inputs += sorted(glob.glob(os.path.join(ROOT, "self", "*덤프.gl"))) + [os.path.join(ROOT, "self", "컴파일러.gl")]
    ref_exe = os.path.join(build_dir, "cmp_ref.exe")
    self_exe = os.path.join(build_dir, "cmp_self.exe")
    env = dict(os.environ, GEUL_ROOT=ROOT)
    for f in inputs:
        for x in (ref_exe, self_exe):
            if os.path.exists(x):
                os.remove(x)
        want = subprocess.run([sys.executable, GEULC, f, "-o", ref_exe], capture_output=True)
        got = subprocess.run([exe, f, "-o", self_exe], capture_output=True, stdin=subprocess.DEVNULL, timeout=120, env=env)
        n += 1
        rel = os.path.relpath(f, ROOT)
        if want.returncode != got.returncode or not os.path.exists(self_exe):
            failed += 1
            print(f"  DIFF  {rel} (ref rc={want.returncode}, self rc={got.returncode})")
            print("        self stderr:", got.stderr.decode("utf-8", "replace").strip()[:300])
            continue
        a = open(ref_exe, "rb").read()
        b = open(self_exe, "rb").read()
        if a != b:
            failed += 1
            k = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
            print(f"  DIFF  {rel}: 바이트 불일치, 첫 차이 오프셋 0x{k:X} (ref {len(a)}B, self {len(b)}B) ref={a[k:k+8].hex()} self={b[k:k+8].hex()}")
    print(f"[컴파일러] exe 바이트 비교 {n}개, 불일치 {failed}개")
    dlls = pe_imports(exe)
    print(f"[컴파일러] 임포트 DLL: {dlls}")
    if any(d.lower().startswith(("msvcr", "ucrt", "api-ms-win-crt")) for d in dlls):
        print("[컴파일러] C 런타임 DLL 을 임포트합니다 — 런타임 독립 위반")
        failed += 1
    # 고정점: self1(ref 가 만든 글 컴파일러) → self2 → self3 이 모두 같은 바이트여야 한다
    import hashlib
    src = os.path.join(ROOT, "self", "컴파일러.gl")
    gens = [exe]
    for k in (2, 3):
        out = os.path.join(build_dir, f"self{k}_컴파일러.exe")
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run([gens[-1], src, "-o", out], capture_output=True, stdin=subprocess.DEVNULL, timeout=300, env=env)
        if r.returncode != 0 or not os.path.exists(out):
            print(f"  고정점 {k}세대 빌드 실패: {r.stderr.decode(chr(117)+chr(116)+chr(102)+chr(45)+chr(56), chr(114)+chr(101)+chr(112)+chr(108)+chr(97)+chr(99)+chr(101))[:300]}")
            return failed + 1
        gens.append(out)
    hashes = [hashlib.sha256(open(g, "rb").read()).hexdigest() for g in gens]
    for k, (g, h) in enumerate(zip(gens, hashes), 1):
        print(f"  {k}세대 {os.path.relpath(g, ROOT)} sha256={h[:16]}… ({os.path.getsize(g)}B)")
    if len(set(hashes)) == 1:
        print("[컴파일러] 고정점 도달: 1·2·3세대 바이트 동일")
    else:
        print("[컴파일러] 고정점 실패: 세대 간 바이트가 다릅니다")
        failed += 1
    return failed


def cmd_selfhost(args):
    """자체호스팅 단계별 교차 검증. 지금은 1단계(렉서): self/렉서.gl 을 ref 로 빌드해 토큰 덤프를 비교한다."""
    build_dir = os.path.join(ROOT, "build")
    os.makedirs(build_dir, exist_ok=True)
    stages = [("토큰덤프", "--dump-tokens"), ("구문덤프", "--dump-ast"), ("IR덤프", "--dump-ir"), ("컴파일러", None)]
    if args:
        stages = [st for st in stages if st[0] in args]
    failed = 0
    for name, opt in stages:
        src = os.path.join(ROOT, "self", f"{name}.gl")
        exe = os.path.join(build_dir, f"self_{name}.exe")
        r = subprocess.run([sys.executable, GEULC, src, "-o", exe], capture_output=True)
        if r.returncode != 0 or not os.path.exists(exe):
            print(f"[{name}] 빌드 실패:\n{(r.stdout + r.stderr).decode('utf-8', 'replace')}")
            return 1
        print(f"[{name}] 빌드 OK → {os.path.relpath(exe, ROOT)}")
        if opt is None:
            failed += selfhost_exe_stage(exe, build_dir)
            continue
        n = 0
        for f in selfhost_inputs():
            want = subprocess.run([sys.executable, GEULC, opt, f], capture_output=True)
            env = dict(os.environ, GEUL_ROOT=ROOT)
            got = subprocess.run([exe, f], capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env=env)
            w = want.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
            g = got.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
            n += 1
            if w != g or want.returncode != got.returncode:
                failed += 1
                rel = os.path.relpath(f, ROOT)
                print(f"  DIFF  {rel} (ref rc={want.returncode}, self rc={got.returncode})")
                wl, gl = w.splitlines(), g.splitlines()
                for k in range(max(len(wl), len(gl))):
                    a = wl[k] if k < len(wl) else "<없음>"
                    b = gl[k] if k < len(gl) else "<없음>"
                    if a != b:
                        print(f"        줄 {k + 1}: ref={a!r}\n                self={b!r}")
                        break
                if got.stderr:
                    print("        self stderr:", got.stderr.decode("utf-8", "replace").strip()[:200])
        print(f"[{name}] 비교 {n}개, 불일치 {failed}개")
        if name == "IR덤프":
            # 부정 테스트: 종료 코드 1 + expect.errors 의 메시지 조각이 자체 구현의 stderr 에도 있어야 한다
            nn = 0
            for f in selfhost_inputs(negative=True):
                env = dict(os.environ, GEUL_ROOT=ROOT)
                got = subprocess.run([exe, f], capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env=env)
                err = got.stderr.decode("utf-8", "replace")
                want = [l.strip() for l in open(os.path.join(os.path.dirname(f), "expect.errors"), encoding="utf-8") if l.strip()]
                missing = [w for w in want if w not in err]
                ref = subprocess.run([sys.executable, GEULC, f, "-o", os.path.join(build_dir, "neg_ref.exe")], capture_output=True)
                ref_line = (ref.stdout + ref.stderr).decode("utf-8", "replace").strip().splitlines()[:1]
                self_line = err.strip().splitlines()[:1]
                nn += 1
                if got.returncode != 1 or missing or ref_line != self_line:
                    failed += 1
                    print(f"  DIFF  {os.path.relpath(f, ROOT)} (self rc={got.returncode}) 기대 메시지 없음: {missing}")
                    print("        ref :", ref_line)
                    print("        self:", self_line)
            print(f"[{name}] 부정 테스트 {nn}개: 오류 줄(파일:줄:열: 메시지) 동일 확인")
    return 0 if failed == 0 else 1


def main(argv):
    if not argv or argv[0] not in ("test", "check", "selfhost"):
        print(__doc__)
        return 3
    if argv[0] == "test":
        return cmd_test(argv[1:])
    if argv[0] == "selfhost":
        return cmd_selfhost(argv[1:])
    return cmd_check(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
