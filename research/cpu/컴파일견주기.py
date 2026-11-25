"""두 컴파일러로 같은 입력을 번갈아 컴파일해 컴파일 시간을 견준다 — 컴파일러 자신의 속도를 바꾼 전후 비교.

    python -I -X utf8 research/cpu/컴파일견주기.py <옛 컴파일러 exe> [--새 <exe>] [--횟수 15] [입력.gl ...]

- 새 컴파일러의 기본값은 build/self_컴파일러.exe, 입력의 기본값은 자체 컴파일러 자신(self/컴파일러.gl)과 프로그램/백업창.gl.
- 두 쪽 모두 이 저장소의 표준/ 을 쓴다. 데운 뒤 --횟수 번, 차례를 바꿔 가며 번갈아 — 프로세스 전체 벽시계 시간의 중앙값.
- 어디서 시간을 쓰는지는 표본재기.py 로 컴파일러 자신을 잰다:
  python -I -X utf8 research/cpu/표본재기.py self/컴파일러.gl -- self/컴파일러.gl -o build/표본.exe   (저장소 꼭대기에서)
"""
import argparse, os, shutil, statistics, subprocess, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ENV = dict(os.environ, GEUL_ROOT=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("옛")
    ap.add_argument("--새", default=os.path.join(ROOT, "build", "self_컴파일러.exe"))
    ap.add_argument("--횟수", type=int, default=15)
    ap.add_argument("입력", nargs="*", default=[os.path.join(ROOT, "self", "컴파일러.gl"), os.path.join(ROOT, "프로그램", "백업창.gl")])
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="geul_cmp_")
    out = os.path.join(tmp, "o.exe")

    def once(c, src):
        t0 = time.perf_counter()
        subprocess.run([c, src, "-o", out], check=True, env=ENV, cwd=ROOT, capture_output=True)
        return time.perf_counter() - t0

    print(f"옛: {a.옛}\n새: {a.새}")
    for src in a.입력:
        for c in (a.옛, a.새):
            once(c, src)                                  # 데우기
        ts = {a.옛: [], a.새: []}
        for r in range(a.횟수):
            for c in ([a.옛, a.새] if r % 2 == 0 else [a.새, a.옛]):
                ts[c].append(once(c, src))
        mo, mn = statistics.median(ts[a.옛]), statistics.median(ts[a.새])
        print(f"{os.path.relpath(src, ROOT):28s} 옛 {mo * 1000:7.1f} ms | 새 {mn * 1000:7.1f} ms | {mo / mn:4.2f}배", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
