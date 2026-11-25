"""두 컴파일러가 모든 입력 · 모든 출력 모드에서 같은 것을 내는가 — 컴파일러의 안쪽만 바꾸는 고침(속도 등)의 검증.

    python -I -X utf8 research/cpu/출력견주기.py <옛 컴파일러 exe> [<새 컴파일러 exe>]

- 새 컴파일러의 기본값은 build/self_컴파일러.exe. 옛 컴파일러는 고치기 전에 build/self_컴파일러.exe 를 다른 폴더로 복사해 둔다.
- 입력: spec-tests 의 모든 main.gl(긍정 · 부정, opts.txt 의 옵션 포함), 표준/*.gl, self/*.gl, 프로그램/*.gl, research/**/*.gl.
- 모드: 실행 파일(윈도), --대상 리눅스, --핫스왑, --dump-ir, --dump-calls, --dump-risky, --check.
- 견주는 것: 종료 코드, 표준출력, 표준오류(오류 메시지), 출력 파일의 바이트. 두 쪽 모두 이 저장소의 표준/ 을 쓴다 — 표준 라이브러리를
  바꾼 고침이면 실행 파일이 달라지는 것이 맞으니 이 도구의 대상이 아니다. 하나라도 다르면 종료 코드 1.
"""
import concurrent.futures as cf, glob, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ENV = dict(os.environ, GEUL_ROOT=ROOT)
MODES = [("실행 파일", []), ("리눅스", ["--대상", "리눅스"]), ("핫스왑", ["--핫스왑"]), ("dump-ir", ["--dump-ir"]),
         ("dump-calls", ["--dump-calls"]), ("dump-risky", ["--dump-risky"]), ("check", ["--check"])]


def inputs():
    out = []
    for m in sorted(glob.glob(os.path.join(ROOT, "spec-tests", "*", "*", "main.gl"))):
        p = os.path.join(os.path.dirname(m), "opts.txt")
        out.append((m, [l.strip() for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []))
    for pat in ["표준/*.gl", "self/*.gl", "프로그램/*.gl", "research/**/*.gl"]:
        out += [(p, []) for p in sorted(glob.glob(os.path.join(ROOT, pat), recursive=True))]
    return out


def run(compiler, src, opts, outdir):
    out = os.path.join(outdir, "o.bin")
    r = subprocess.run([compiler, src, *opts, "-o", out], capture_output=True, env=ENV, cwd=ROOT)
    data = open(out, "rb").read() if os.path.exists(out) else None
    return r.returncode, r.stdout, r.stderr, data


def job(args):
    old, new, src, opts, mname, mopts = args
    a, b = tempfile.mkdtemp(prefix="geul_out_a_"), tempfile.mkdtemp(prefix="geul_out_b_")
    try:
        ra, rb = run(old, src, [*opts, *mopts], a), run(new, src, [*opts, *mopts], b)
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)
    what = [k for k, x, y in zip(("종료 코드", "표준출력", "표준오류", "출력 파일"), ra, rb) if x != y]
    return src, mname, what


def main():
    old = sys.argv[1]
    new = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "build", "self_컴파일러.exe")
    srcs = inputs()
    jobs = [(old, new, s, o, mn, mo) for s, o in srcs for mn, mo in MODES]
    count = {mn: [0, 0] for mn, _ in MODES}
    bad = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for src, mname, what in ex.map(job, jobs):
            count[mname][0] += 1
            count[mname][1] += not what
            if what:
                bad.append((os.path.relpath(src, ROOT), mname, what))
    print(f"입력 {len(srcs)} 개 × 모드 {len(MODES)} = {len(jobs)} 번 — 같음 {len(jobs) - len(bad)}, 다름 {len(bad)}")
    for mname, (n, ok) in count.items():
        print(f"  {mname:10s} {ok}/{n}")
    for b in bad[:30]:
        print("  다름:", b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
