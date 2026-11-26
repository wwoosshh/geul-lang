"""표준 라이브러리를 바꾼 전후의 함수별 시간 — 같은 재기 프로그램([표준재기.gl](표준재기.gl))을 두 루트로 만들어 작업마다 견준다.

    python -I -X utf8 research/cpu/표준견주기.py <옛 루트> [<새 루트>] [--횟수 9] [--만 글자수 키워드 ...] [--코어 P|E|없음] [--출력 결과.json]

- 루트마다 build/self_컴파일러.exe 와 표준/ 이 있어야 한다(새 루트의 기본값은 이 저장소) — 판견주기.py 와 같다. 컴파일러가 같아도
  표준이 다르면 실행 파일에 든 표준 함수가 다르다. 옛 루트는 고치기 전에 떠 둔다(`git archive <태그> ref self 표준 | tar -x -C <폴더>` 뒤
  `python ref/geulc.py self/컴파일러.gl -o build/self_컴파일러.exe`).
- 작업마다 두 실행 파일의 출력(한 줄)이 같아야 잰다. 데운 뒤 --횟수 번, 두 실행 파일을 번갈아(차례를 바꿔 가며) 돌린 벽시계 시간의
  중앙값. 파일 쓰기 작업은 임시 폴더에 쓰고 지운다.
"""
import argparse, json, os, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from 언어견주기 import pin, cpu_name  # noqa: E402
from 판견주기 import build  # noqa: E402

일들 = ["글자수", "짧은글자수", "긴비교", "짧은비교", "키워드", "메모리비교", "서식", "정수서식", "파일쓰기", "텍스트쓰기"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("옛")
    ap.add_argument("새", nargs="?", default=ROOT)
    ap.add_argument("--횟수", type=int, default=9)
    ap.add_argument("--만", nargs="*", default=일들)
    ap.add_argument("--코어", default="P", choices=["P", "E", "없음"])
    ap.add_argument("--출력")
    a = ap.parse_args()
    묶음 = pin(a.코어)
    tmp = tempfile.mkdtemp(prefix="geul_std_")
    src = os.path.join(tmp, "표준재기.gl")
    with open(os.path.join(HERE, "표준재기.gl"), "rb") as f, open(src, "wb") as g:
        g.write(f.read())
    eo, en = os.path.join(tmp, "옛.exe"), os.path.join(tmp, "새.exe")
    build(a.옛, src, eo)
    build(a.새, src, en)
    print(f"옛: {a.옛}\n새: {a.새}\nCPU: {cpu_name()} — 묶은 논리 CPU {묶음 or '없음'}")
    결과 = {"정보": {"옛": a.옛, "새": a.새, "cpu": cpu_name(), "묶은 논리 CPU": 묶음, "횟수": a.횟수}, "작업": {}}
    for w in a.만:
        oo = subprocess.run([eo, w], capture_output=True, cwd=tmp).stdout
        on = subprocess.run([en, w], capture_output=True, cwd=tmp).stdout
        if oo != on:
            sys.exit(f"{w}: 출력이 다르다 {oo!r} / {on!r}")
        ts = {eo: [], en: []}
        for r in range(a.횟수):
            for e in ([eo, en] if r % 2 == 0 else [en, eo]):
                t0 = time.perf_counter()
                subprocess.run([e, w], stdout=subprocess.DEVNULL, cwd=tmp)
                ts[e].append(time.perf_counter() - t0)
        mo, mn = statistics.median(ts[eo]), statistics.median(ts[en])
        결과["작업"][w] = {"옛": ts[eo], "새": ts[en], "옛 가운데": mo, "새 가운데": mn}
        print(f"{w:7s} 옛 {mo:6.3f} s | 새 {mn:6.3f} s | {mo / mn:5.2f} 배", flush=True)
    if a.출력:
        with open(a.출력, "w", encoding="utf-8") as f:
            json.dump(결과, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
