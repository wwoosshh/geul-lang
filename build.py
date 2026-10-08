#!/usr/bin/env python3
"""글 2세대 단일 빌드 진입점 (D-08).

  python build.py test [필터] [--self]  spec-tests 실행 (컴파일 실패 = 실패, 건너뜀 없음; --self: 글로 쓴 컴파일러 build/self_컴파일러.exe 로)
                                    테스트의 opts.txt 는 컴파일러 옵션 (D-46) — 모든 단계가 양쪽 구현에 같이 준다
  python build.py test --핫스왑 [--self]  핫스왑 투명성: 긍정 테스트 전부를 --핫스왑 으로 빌드해 같은 기대값과 맞춘다
  python build.py check <파일.gl>  문법·의미 검사
  python build.py selfhost [단계]  자체호스팅 단계별 교차 검증 (단계: 토큰덤프 구문덤프 IR덤프 컴파일러 — 마지막은 exe 바이트 비교 + 고정점 + 명령줄)
  python build.py docs [필터]      문서의 ```글 예제를 컴파일·실행해 ```출력 과 맞춘다
  python build.py tools           프로그램/ 의 도구들을 만들어 본다
  python build.py release          배포물 만들기: dist/geul-<버전>-windows-x64/ (자기 컴파일한 geulc.exe + 표준/ + 문서) 와 zip
  python build.py wheel [--대조 <릴리스.zip>]  PyPI 휠 (D-47): release 다음 geulc.exe·표준/ + 런처를 묶고 가상환경 설치 연기 시험
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


IR_OPTS = ("--핫스왑", "--hotswap")    # IR 을 바꾸는 옵션 (교체 허용, 인라인 끔). 덤프 드라이버는 이것만 받는다
EXTRA_OPTS = []                         # test --핫스왑: 모든 긍정 테스트에 더하는 옵션 (투명성 검사)


def test_opts(path):
    """수용 테스트의 컴파일러 옵션: 테스트 디렉터리의 opts.txt, 한 줄에 하나 (D-46). spec-tests 밖(표준/, self/)은 없음."""
    d = path if os.path.isdir(path) else os.path.dirname(path)
    if not os.path.abspath(d).startswith(TESTS + os.sep):
        return []
    return [l.strip() for l in read(os.path.join(d, "opts.txt")).splitlines() if l.strip()]


def run_test(test_dir, verbose):
    name = os.path.relpath(test_dir, TESTS).replace("\\", "/")
    main = os.path.join(test_dir, "main.gl")
    errors_file = os.path.join(test_dir, "expect.errors")
    opts = test_opts(test_dir)
    opts += [o for o in EXTRA_OPTS if o not in opts]
    tmp = tempfile.mkdtemp(prefix="geul-")
    try:
        exe = os.path.join(tmp, "main.exe")
        t0 = time.time()
        try:
            r = subprocess.run(COMPILER + [main, "-o", exe] + opts, capture_output=True, timeout=60, stdin=subprocess.DEVNULL, env=COMPILER_ENV)
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
        errs = read(os.path.join(test_dir, "expect.stderr"), "")
        if errs:
            got_err = rr.stderr.decode("utf-8", "replace").replace("\r\n", "\n")
            missing = [l for l in errs.splitlines() if l.strip() and l.strip() not in got_err]
            if missing:
                problems.append(f"표준오류에 없음: {missing}\n--- 실제\n{got_err}")
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
    if "--핫스왑" in args or "--hotswap" in args:
        # 핫스왑 투명성 (D-42): 함수 테이블 우회는 동작을 바꾸지 않는다. 대상은 긍정 테스트 전부 —
        # 부정 테스트는 옵션이 오류를 바꿀 수 있으므로(교체 허용) 이 검사의 모집단이 아니다.
        EXTRA_OPTS.append("--핫스왑")
        dirs = [d for d in dirs if not os.path.exists(os.path.join(d, "expect.errors"))]
        print(f"핫스왑 투명성: 긍정 테스트 {len(dirs)}개를 --핫스왑 으로 — 출력·종료 코드가 기본 빌드의 기대값과 같아야 한다")
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


def read_version():
    return open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()


def check_version_file():
    """self/버전.gl 의 컴파일러_버전 은 VERSION 과 같아야 한다."""
    v = read_version()
    src = read(os.path.join(ROOT, "self", "버전.gl"))
    if f'"{v}"' not in src:
        print(f"self/버전.gl 의 버전이 VERSION({v})과 다릅니다 — self/버전.gl 을 고치세요")
        return False
    return True


def cmd_release(args):
    """배포물: ref 가 만든 geulc 로 다시 geulc 를 만들어(자기 컴파일) 바이트가 같은지 확인한 뒤 묶는다."""
    import hashlib, zipfile
    if not check_version_file():
        return 1
    version = read_version()
    build_dir = os.path.join(ROOT, "build", "release")
    os.makedirs(build_dir, exist_ok=True)
    env = dict(os.environ, GEUL_ROOT=ROOT)
    src = os.path.join(ROOT, "self", "컴파일러.gl")
    gen1 = os.path.join(build_dir, "geulc1.exe")
    gen2 = os.path.join(build_dir, "geulc.exe")
    for x in (gen1, gen2):
        if os.path.exists(x):
            os.remove(x)
    r = subprocess.run([sys.executable, GEULC, src, "-o", gen1], capture_output=True)
    if r.returncode != 0:
        print("1세대 빌드 실패:", (r.stdout + r.stderr).decode("utf-8", "replace")[:500])
        return 1
    r = subprocess.run([gen1, src, "-o", gen2], capture_output=True, stdin=subprocess.DEVNULL, timeout=300, env=env)
    if r.returncode != 0 or not os.path.exists(gen2):
        print("자기 컴파일 실패:", r.stderr.decode("utf-8", "replace")[:500])
        return 1
    h1 = hashlib.sha256(open(gen1, "rb").read()).hexdigest()
    h2 = hashlib.sha256(open(gen2, "rb").read()).hexdigest()
    if h1 != h2:
        print("자기 컴파일 결과가 참조 구현의 결과와 다릅니다 — 배포 중단")
        return 1
    name = f"geul-{version}-windows-x64"
    dist = os.path.join(ROOT, "dist", name)
    if os.path.exists(dist):
        shutil.rmtree(dist)
    os.makedirs(dist)
    shutil.copy(gen2, os.path.join(dist, "geulc.exe"))
    shutil.copytree(os.path.join(ROOT, "표준"), os.path.join(dist, "표준"))
    os.makedirs(os.path.join(dist, "docs"))
    for d in ("03-문법-명세.md", "05-덤프-형식.md", "06-표준-라이브러리.md"):
        shutil.copy(os.path.join(ROOT, "docs", d), os.path.join(dist, "docs", d))
    for f in ("README.md", "LICENSE", "VERSION"):
        shutil.copy(os.path.join(ROOT, f), os.path.join(dist, f))
    os.makedirs(os.path.join(dist, "예제"))
    for ex in ("01-안녕", "02-계산", "08-보간-종합"):
        srcdir = os.path.join(TESTS, "프로그램-예제", ex)
        if os.path.isdir(srcdir):
            shutil.copy(os.path.join(srcdir, "main.gl"), os.path.join(dist, "예제", ex + ".gl"))
    # 연기 시험: 배포 디렉터리의 geulc 로, GEUL_ROOT 없이, 다른 디렉터리에서 컴파일·실행
    tmp = tempfile.mkdtemp(prefix="geul-release-")
    try:
        hello = os.path.join(tmp, "안녕.gl")
        open(hello, "w", encoding="utf-8", newline=chr(10)).write('[시작하기]는 -> 정수 {' + chr(10) + '    "안녕, 글 %s\\n"을 "배포판"을 쓰다.' + chr(10) + '    반환 0.' + chr(10) + '}' + chr(10))
        clean_env = {k: v for k, v in os.environ.items() if k != "GEUL_ROOT"}
        r = subprocess.run([os.path.join(dist, "geulc.exe"), hello], capture_output=True, cwd=tmp, env=clean_env, timeout=120)
        exe = os.path.join(tmp, "안녕.exe")
        if r.returncode != 0 or not os.path.exists(exe):
            print("연기 시험 실패 (컴파일):", r.stderr.decode("utf-8", "replace")[:300])
            return 1
        rr = subprocess.run([exe], capture_output=True, cwd=tmp, timeout=30)
        out = rr.stdout.decode("utf-8", "replace").replace(chr(13), "")
        if rr.returncode != 0 or out != "안녕, 글 배포판" + chr(10):
            print("연기 시험 실패 (실행):", rr.returncode, repr(out))
            return 1
        rv = subprocess.run([os.path.join(dist, "geulc.exe"), "--version"], capture_output=True, cwd=tmp, env=clean_env, timeout=30)
        ver_line = rv.stdout.decode("utf-8", "replace").strip()
        if version not in ver_line:
            print("연기 시험 실패 (--version):", repr(ver_line))
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    zpath = os.path.join(ROOT, "dist", name + ".zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(dist):
            for f in files:
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, os.path.dirname(dist)))
    sha = hashlib.sha256(open(zpath, "rb").read()).hexdigest()
    open(zpath + ".sha256", "w", encoding="utf-8", newline=chr(10)).write(f"{sha}  {name}.zip" + chr(10))
    print(f"배포물: {os.path.relpath(dist, ROOT)}  ({os.path.getsize(gen2)}B geulc.exe, sha256 {h2[:16]}…)")
    print(f"zip: {os.path.relpath(zpath, ROOT)}  sha256 {sha[:16]}…")
    print(f"연기 시험 통과: GEUL_ROOT 없이 안녕.gl 컴파일·실행, --version = {ver_line}")
    return 0


WHEEL_TAG = "py3-none-win_amd64"
PYPI_DIR = os.path.join(ROOT, "packaging", "pypi")


def wheel_metadata(version):
    """휠의 METADATA (Metadata-Version 2.1). 긴 설명은 packaging/pypi/README.md."""
    head = [
        "Metadata-Version: 2.1",
        "Name: geul",
        f"Version: {version}",
        "Summary: 글 — 한국어 문법(SOV·조사)으로 쓰는 자체호스팅 시스템 언어의 컴파일러 (Windows x64)",
        "Author: wwoosshh",
        "License: MIT",
        "Project-URL: Homepage, https://github.com/wwoosshh/geul-lang/tree/v2",
        "Project-URL: Source, https://github.com/wwoosshh/geul-lang",
        "Project-URL: Releases, https://github.com/wwoosshh/geul-lang/releases",
        "Keywords: korean,hangul,compiler,programming-language,self-hosting",
        "Classifier: Environment :: Console",
        "Classifier: Intended Audience :: Developers",
        "Classifier: Intended Audience :: Education",
        "Classifier: License :: OSI Approved :: MIT License",
        "Classifier: Natural Language :: Korean",
        "Classifier: Operating System :: Microsoft :: Windows",
        "Classifier: Programming Language :: Other",
        "Classifier: Topic :: Software Development :: Compilers",
        "Requires-Python: >=3.8",
        "Description-Content-Type: text/markdown; charset=UTF-8",
    ]
    return "\n".join(head) + "\n\n" + read(os.path.join(PYPI_DIR, "README.md"))


def wheel_smoke(whl, version):
    """임시 가상환경에 휠을 설치하고, 다른 폴더(한글·공백 경로)에서 GEUL_ROOT 없이 geulc 로 컴파일·실행해 본다."""
    tmp = tempfile.mkdtemp(prefix="geul-wheel-")
    try:
        venv = os.path.join(tmp, "venv")
        r = subprocess.run([sys.executable, "-m", "venv", venv], capture_output=True)
        if r.returncode != 0:
            print("휠 연기 시험 실패 (가상환경):", (r.stdout + r.stderr).decode("utf-8", "replace")[-300:])
            return False
        py = os.path.join(venv, "Scripts", "python.exe")
        r = subprocess.run([py, "-m", "pip", "install", "--no-index", "--no-deps", "--disable-pip-version-check", "-q", whl],
                           capture_output=True)
        if r.returncode != 0:
            print("휠 연기 시험 실패 (pip install):", (r.stdout + r.stderr).decode("utf-8", "replace")[-500:])
            return False
        geulc = os.path.join(venv, "Scripts", "geulc.exe")
        work = os.path.join(tmp, "작업 폴더")
        os.makedirs(work)
        open(os.path.join(work, "안녕.gl"), "w", encoding="utf-8", newline=chr(10)).write(
            '[시작하기]는 -> 정수 {' + chr(10) + '    "안녕, 글 %s\\n"을 "휠"을 쓰다.' + chr(10) + '    반환 0.' + chr(10) + '}' + chr(10))
        open(os.path.join(work, "틀림.gl"), "w", encoding="utf-8", newline=chr(10)).write(
            '[시작하기]는 -> 정수 { 반환 없는이름. }' + chr(10))
        clean_env = {k: v for k, v in os.environ.items() if k != "GEUL_ROOT"}
        r = subprocess.run([geulc, "안녕.gl"], cwd=work, env=clean_env, capture_output=True, timeout=120)
        exe = os.path.join(work, "안녕.exe")
        if r.returncode != 0 or not os.path.exists(exe):
            print("휠 연기 시험 실패 (컴파일):", (r.stdout + r.stderr).decode("utf-8", "replace")[-300:])
            return False
        rr = subprocess.run([exe], cwd=work, capture_output=True, timeout=30)
        out = rr.stdout.decode("utf-8", "replace").replace(chr(13), "")
        if rr.returncode != 0 or out != "안녕, 글 휠" + chr(10):
            print("휠 연기 시험 실패 (실행):", rr.returncode, repr(out))
            return False
        r = subprocess.run([geulc, "틀림.gl"], cwd=work, env=clean_env, capture_output=True, timeout=120)
        if r.returncode != 1:
            print(f"휠 연기 시험 실패: 틀린 프로그램의 종료 코드가 1 이 아니라 {r.returncode} — 런처가 종료 코드를 잃는다")
            return False
        rv = subprocess.run([py, "-m", "geul", "--version"], cwd=work, env=clean_env, capture_output=True, timeout=30)
        rm = subprocess.run([py, "-c", "import geul; print(geul.__version__)"], cwd=work, capture_output=True, timeout=30)
        if version not in rv.stdout.decode("utf-8", "replace") or rm.stdout.decode().strip() != version:
            print("휠 연기 시험 실패 (판 번호):", repr(rv.stdout), repr(rm.stdout))
            return False
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_wheel(args):
    """PyPI 휠 (D-47): release 가 검증한 배포 디렉터리의 geulc.exe 와 표준/ 을 geul-<버전>-py3-none-win_amd64.whl 로 묶는다.
    --대조 <릴리스.zip> 이면 먼저 그 zip 의 geulc.exe·표준/ 과 바이트가 같은지 본다 (게시 워크플로가 GitHub 릴리스로 쓴다)."""
    import base64, hashlib, zipfile
    version = read_version()
    name = f"geul-{version}-windows-x64"
    ref = None
    if "--대조" in args:
        k = args.index("--대조")
        if k + 1 >= len(args):
            print("사용법: build.py wheel [--대조 <릴리스.zip>]")
            return 3
        # release 가 dist/ 의 zip 을 다시 쓰므로 비교할 내용은 먼저 읽어 둔다
        with zipfile.ZipFile(args[k + 1]) as z:
            ref = {n[len(name) + 1:]: z.read(n) for n in z.namelist()
                   if n == f"{name}/geulc.exe" or n.startswith(f"{name}/표준/")}
    rc = cmd_release([])
    if rc != 0:
        return rc
    rel = os.path.join(ROOT, "dist", name)
    payload = [("geulc.exe", open(os.path.join(rel, "geulc.exe"), "rb").read())]
    payload += [(f"표준/{f}", open(os.path.join(rel, "표준", f), "rb").read()) for f in sorted(os.listdir(os.path.join(rel, "표준")))]
    if ref is not None:
        bad = [p for p, data in payload if ref.get(p) != data] + sorted(set(ref) - {p for p, _ in payload})
        if bad:
            print(f"릴리스 대조 실패: {os.path.basename(args[args.index('--대조') + 1])} 와 다른 파일 {bad}")
            return 1
        print(f"릴리스 대조: geulc.exe·표준/ {len(payload)}개 파일이 릴리스 zip 과 바이트 동일")
    entries = [(f"geul/{f}", open(os.path.join(PYPI_DIR, "geul", f), "rb").read()) for f in ("__init__.py", "__main__.py")]
    entries += [(f"geul/{p}", data) for p, data in payload]
    info = f"geul-{version}.dist-info"
    entries += [
        (f"{info}/METADATA", wheel_metadata(version).encode("utf-8")),
        (f"{info}/WHEEL", f"Wheel-Version: 1.0\nGenerator: geul build.py wheel\nRoot-Is-Purelib: false\nTag: {WHEEL_TAG}\n".encode()),
        (f"{info}/entry_points.txt", b"[console_scripts]\ngeulc = geul.__main__:main\n"),
        (f"{info}/LICENSE", open(os.path.join(ROOT, "LICENSE"), "rb").read()),
    ]
    record = [f"{n},sha256={base64.urlsafe_b64encode(hashlib.sha256(d).digest()).rstrip(b'=').decode()},{len(d)}" for n, d in entries]
    record.append(f"{info}/RECORD,,")
    entries.append((f"{info}/RECORD", ("\n".join(record) + "\n").encode("utf-8")))
    whl = os.path.join(ROOT, "dist", f"geul-{version}-{WHEEL_TAG}.whl")
    if os.path.exists(whl):
        os.remove(whl)
    with zipfile.ZipFile(whl, "w") as z:          # 결정적: 고정 시각, 고정 순서, 고정 권한
        for n, d in entries:
            zi = zipfile.ZipInfo(n, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, d)
    sha = hashlib.sha256(open(whl, "rb").read()).hexdigest()
    print(f"휠: {os.path.relpath(whl, ROOT)}  ({os.path.getsize(whl)}B, 파일 {len(entries)}개, sha256 {sha[:16]}…)")
    if not wheel_smoke(whl, version):
        return 1
    print("휠 연기 시험 통과: 임시 가상환경에 설치, 한글·공백 폴더에서 GEUL_ROOT 없이 geulc 로 컴파일·실행, 오류 종료 코드 전달, python -m geul --version")
    return 0


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
        o = test_opts(f)
        want = subprocess.run([sys.executable, GEULC, f, "-o", ref_exe] + o, capture_output=True)
        got = subprocess.run([exe, f, "-o", self_exe] + o, capture_output=True, stdin=subprocess.DEVNULL, timeout=120, env=env)
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
    if not check_version_file():
        return 1
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
            failed += selfhost_calls_stage(exe)
            failed += selfhost_cli_stage(exe, build_dir)
            continue
        n = 0
        for f in selfhost_inputs():
            # 토큰·구문 덤프는 옵션과 무관하다. IR 은 --핫스왑 이면 달라지므로(교체 허용, 인라인 끔) 그 옵션을 양쪽에 준다.
            o = [x for x in test_opts(f) if x in IR_OPTS] if name == "IR덤프" else []
            want = subprocess.run([sys.executable, GEULC, opt, f] + o, capture_output=True)
            env = dict(os.environ, GEUL_ROOT=ROOT)
            got = subprocess.run([exe] + o + [f], capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env=env)
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
                o = [x for x in test_opts(f) if x in IR_OPTS]
                got = subprocess.run([exe] + o + [f], capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env=env)
                err = got.stderr.decode("utf-8", "replace")
                want = [l.strip() for l in open(os.path.join(os.path.dirname(f), "expect.errors"), encoding="utf-8") if l.strip()]
                missing = [w for w in want if w not in err]
                ref = subprocess.run([sys.executable, GEULC, f, "-o", os.path.join(build_dir, "neg_ref.exe")] + test_opts(f), capture_output=True)
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


def selfhost_calls_stage(exe):
    """호출 색인(--dump-calls) 이 두 구현에서 같은가 (D-24)."""
    bad = 0
    n = 0
    env = dict(os.environ, GEUL_ROOT=ROOT)
    for f in selfhost_inputs():
        o = test_opts(f)
        want = subprocess.run([sys.executable, GEULC, f, "--dump-calls"] + o, capture_output=True)
        got = subprocess.run([exe, f, "--dump-calls"] + o, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env=env)
        w = want.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
        g = got.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
        n += 1
        if w != g:
            bad += 1
            wl, gl = w.splitlines(), g.splitlines()
            print(f"  DIFF  {os.path.relpath(f, ROOT)} 호출 색인")
            for k in range(max(len(wl), len(gl))):
                a = wl[k] if k < len(wl) else "<없음>"
                b = gl[k] if k < len(gl) else "<없음>"
                if a != b:
                    print(f"        줄 {k + 1}: ref={a!r}\n                self={b!r}")
                    break
    print(f"[컴파일러] 호출 색인 비교 {n}개, 불일치 {bad}개")
    bad2 = 0
    for f in selfhost_inputs():
        o = test_opts(f)
        want = subprocess.run([sys.executable, GEULC, f, "--dump-risky"] + o, capture_output=True)
        got = subprocess.run([exe, f, "--dump-risky"] + o, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env=env)
        w = want.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
        g = got.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
        if w != g:
            bad2 += 1
            print(f"  DIFF  {os.path.relpath(f, ROOT)} 위험 보고")
    print(f"[컴파일러] 위험 보고 비교 {n}개, 불일치 {bad2}개")
    return bad + bad2


def selfhost_cli_stage(exe, build_dir):
    """배포되는 컴파일러의 명령줄 (명세 6절): --dump-ir 와 --check 가 참조 구현과 같은가."""
    bad = 0
    env = dict(os.environ, GEUL_ROOT=ROOT)

    def norm(b):
        return b.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")

    # --dump-ir: 덤프 드라이버 대신 컴파일러로. 옵션이 있는 테스트(핫스왑)와 컴파일러 자신
    ir_inputs = [f for f in selfhost_inputs() if test_opts(f)] + [os.path.join(ROOT, "self", "컴파일러.gl")]
    for f in ir_inputs:
        o = test_opts(f)
        want = subprocess.run([sys.executable, GEULC, f, "--dump-ir"] + o, capture_output=True)
        got = subprocess.run([exe, f, "--dump-ir"] + o, capture_output=True, stdin=subprocess.DEVNULL, timeout=60, env=env)
        if norm(want.stdout) != norm(got.stdout) or want.returncode != got.returncode:
            bad += 1
            print(f"  DIFF  {os.path.relpath(f, ROOT)} --dump-ir (ref rc={want.returncode}, self rc={got.returncode})")
    # --check: 부정 테스트는 종료 코드 1 과 같은 첫 오류 줄, 맞는 프로그램은 0 이고 출력 파일을 만들지 않는다
    negs = selfhost_inputs(negative=True)
    for f in negs:
        o = test_opts(f)
        want = subprocess.run([sys.executable, GEULC, f, "--check"] + o, capture_output=True)
        got = subprocess.run([exe, f, "--check"] + o, capture_output=True, stdin=subprocess.DEVNULL, timeout=60, env=env)
        wl = norm(want.stdout + want.stderr).splitlines()[:1]
        gl = norm(got.stdout + got.stderr).splitlines()[:1]
        if got.returncode != 1 or want.returncode != 1 or wl != gl:
            bad += 1
            print(f"  DIFF  {os.path.relpath(f, ROOT)} --check (ref rc={want.returncode}, self rc={got.returncode})")
            print("        ref :", wl)
            print("        self:", gl)
    probe = os.path.join(build_dir, "check_probe.exe")
    if os.path.exists(probe):
        os.remove(probe)
    r = subprocess.run([exe, os.path.join(ROOT, "self", "컴파일러.gl"), "--check", "-o", probe],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=60, env=env)
    if r.returncode != 0 or os.path.exists(probe):
        bad += 1
        print(f"  DIFF  --check 가 맞는 프로그램에서 rc={r.returncode}, 출력 파일 {'있음' if os.path.exists(probe) else '없음'}")
    print(f"[컴파일러] 명령줄: --dump-ir {len(ir_inputs)}개, --check 부정 {len(negs)}개 + 긍정 1개, 불일치 {bad}개")
    return bad


def doc_examples(path):
    """문서에서 (프로그램, 기대출력, 줄번호) 를 뽑는다. ```글 뒤에 ```출력 이 오면 한 쌍이다."""
    lines = open(path, encoding="utf-8").read().split("\n")
    out = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```글":
            start = i + 1
            j = start
            while j < len(lines) and lines[j].strip() != "```":
                j += 1
            prog = "\n".join(lines[start:j])
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            want = None
            if k < len(lines) and lines[k].strip() == "```출력":
                m = k + 1
                while m < len(lines) and lines[m].strip() != "```":
                    m += 1
                want = "\n".join(lines[k + 1:m])
                j = m
            out.append((prog, want, start))
            i = j + 1
            continue
        i += 1
    return out


def cmd_docs(args):
    """문서의 예제를 전부 컴파일·실행해 기대 출력과 맞춘다 (D-33)."""
    docs = sorted(glob.glob(os.path.join(ROOT, "docs", "*.md")))
    if args:
        docs = [d for d in docs if any(a in os.path.basename(d) for a in args)]
    total = failed = 0
    for doc in docs:
        pairs = doc_examples(doc)
        if not pairs:
            continue
        name = os.path.basename(doc)
        for prog, want, line in pairs:
            total += 1
            tmp = tempfile.mkdtemp(prefix="glddoc-")
            try:
                src = os.path.join(tmp, "예제.gl")
                open(src, "w", encoding="utf-8", newline="\n").write(prog + "\n")
                exe = os.path.join(tmp, "예제.exe")
                r = subprocess.run([sys.executable, GEULC, src, "-o", exe], capture_output=True)
                if r.returncode != 0:
                    failed += 1
                    msg = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()[:1]
                    print(f"  FAIL  {name}:{line} 컴파일 실패: {msg[0] if msg else ''}")
                    continue
                if want is None:
                    print(f"  PASS  {name}:{line} (컴파일만)")
                    continue
                env = dict(os.environ, GEUL_ROOT=ROOT)
                rr = subprocess.run([exe], capture_output=True, timeout=20, stdin=subprocess.DEVNULL, cwd=tmp, env=env)
                got = rr.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")
                if got != want.rstrip("\n"):
                    failed += 1
                    print(f"  FAIL  {name}:{line} 출력 불일치")
                    print(f"        기대 {want.rstrip(chr(10))!r}")
                    print(f"        실제 {got!r}")
                else:
                    print(f"  PASS  {name}:{line}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n문서 예제: {total - failed}/{total} 통과")
    return 0 if failed == 0 else 1


def cmd_tools(args):
    """프로그램/ 의 도구들을 실제로 만들어 본다. 창 프로그램은 --창 으로."""
    tools = [("프로그램/백업.gl", []), ("프로그램/백업창.gl", ["--창"])]
    tmp = tempfile.mkdtemp(prefix="gltool-")
    failed = 0
    try:
        for rel, opts in tools:
            src = os.path.join(ROOT, rel.replace("/", os.sep))
            if not os.path.exists(src):
                print(f"  SKIP  {rel} (없음)")
                continue
            exe = os.path.join(tmp, os.path.basename(rel)[:-3] + ".exe")
            r = subprocess.run([sys.executable, GEULC, src] + opts + ["-o", exe],
                               capture_output=True, cwd=ROOT)
            if r.returncode != 0:
                failed += 1
                msg = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()[:1]
                print(f"  FAIL  {rel}: {msg[0] if msg else ''}")
                continue
            sub = 0
            with open(exe, "rb") as f:
                d = f.read()
            pe_off = int.from_bytes(d[0x3C:0x40], "little")
            sub = int.from_bytes(d[pe_off + 4 + 20 + 68:pe_off + 4 + 20 + 70], "little")
            want = 2 if "--창" in opts else 3
            if sub != want:
                failed += 1
                print(f"  FAIL  {rel}: 서브시스템 {sub} (기대 {want})")
                continue
            print(f"  PASS  {rel} ({len(d)}B, 서브시스템 {sub})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print(f"프로그램: {len(tools) - failed}/{len(tools)} 만들어짐")
    return 0 if failed == 0 else 1


def main(argv):
    if not argv or argv[0] not in ("test", "check", "selfhost", "release", "wheel", "docs", "tools"):
        print(__doc__)
        return 3
    if argv[0] == "test":
        return cmd_test(argv[1:])
    if argv[0] == "selfhost":
        return cmd_selfhost(argv[1:])
    if argv[0] == "release":
        return cmd_release(argv[1:])
    if argv[0] == "wheel":
        return cmd_wheel(argv[1:])
    if argv[0] == "docs":
        return cmd_docs(argv[1:])
    if argv[0] == "tools":
        return cmd_tools(argv[1:])
    return cmd_check(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
