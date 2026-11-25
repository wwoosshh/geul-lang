"""두 컴파일러(판)가 낸 실행 파일을 같은 기계 · 차례 돌림으로 견준다 — 코드 생성을 바꾼 전후 비교용.

    python -I -X utf8 research/cpu/판견주기.py <옛 루트> [<새 루트>] [--횟수 7] [--만 fib sieve ...]

- 루트마다 build/self_컴파일러.exe 와 표준/ 이 있어야 한다(새 루트의 기본값은 이 저장소). 옛 컴파일러는 고치기 전에 루트째 떠 둔다:
  build/self_컴파일러.exe 와 표준/ 을 다른 폴더로 복사하거나, `git archive <태그> ref self 표준 | tar -x -C <폴더>` 뒤
  `python ref/geulc.py self/컴파일러.gl -o build/self_컴파일러.exe`.
- 같은 소스를 두 컴파일러로 만들고 출력(한 줄)이 같아야 잰다. 데운 뒤 --횟수 번, 두 실행 파일을 번갈아(차례를 바꿔 가며) 돌린 벽시계 시간의
  중앙값. 같은 회차 안에서 견주므로 기계의 흔들림(노트북의 부스트 · 열 — 회차 사이 10 % 남짓)이 두 쪽에 같이 든다.
"""
import argparse, os, shutil, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BENCH = ["fib", "sieve", "bubble", "matmul", "sha256", "rope"]


def build(root, src, exe):
    geulc = os.path.join(root, "build", "self_컴파일러.exe")
    r = subprocess.run([geulc, src, "-o", exe], capture_output=True, env=dict(os.environ, GEUL_ROOT=root), cwd=root)
    if r.returncode != 0:
        sys.exit(f"빌드 실패 {geulc} {src}\n{r.stdout.decode('utf-8', 'replace')}{r.stderr.decode('utf-8', 'replace')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("옛")
    ap.add_argument("새", nargs="?", default=ROOT)
    ap.add_argument("--횟수", type=int, default=7)
    ap.add_argument("--만", nargs="*", default=BENCH)
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="geul_pan_")
    print(f"옛: {a.옛}\n새: {a.새}")
    for b in a.만:
        src = os.path.join(tmp, b + ".gl")
        shutil.copy(os.path.join(HERE, b + ".gl"), src)
        eo, en = os.path.join(tmp, b + "_old.exe"), os.path.join(tmp, b + "_new.exe")
        build(a.옛, src, eo)
        build(a.새, src, en)
        same = open(eo, "rb").read() == open(en, "rb").read()
        oo = subprocess.run([eo], capture_output=True, text=True).stdout.strip()
        on = subprocess.run([en], capture_output=True, text=True).stdout.strip()
        if oo != on:
            sys.exit(f"{b}: 출력이 다르다 {oo!r} / {on!r}")
        ts = {eo: [], en: []}
        for r in range(a.횟수):
            for e in ([eo, en] if r % 2 == 0 else [en, eo]):
                t0 = time.perf_counter()
                subprocess.run([e], capture_output=True)
                ts[e].append(time.perf_counter() - t0)
        mo, mn = statistics.median(ts[eo]), statistics.median(ts[en])
        print(f"{b:7s} 옛 {mo:6.3f} s | 새 {mn:6.3f} s | 새/옛 {mn / mo:4.2f} ({mo / mn:4.2f}배) | "
              f"실행 파일 바이트 {'같음' if same else '다름'}", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
