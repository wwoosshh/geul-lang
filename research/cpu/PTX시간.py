"""PTX 뒷단(글로 쓴 CPU 프로그램)이 GeulPU 의 모듈 여섯을 PTX 로 바꾸는 시간과, 출력이 기록과 바이트까지 같은지.

    python -I -X utf8 research/cpu/PTX시간.py <GeulPU 저장소> [--뒷단 build/자체PTX.exe] [--횟수 1] [--출력 시간.json]

모듈 소스는 <GeulPU>/빌드/글/<이름>.gl (GeulPU 의 생성기가 만든 것), 기대 해시는 <GeulPU>/시험/모듈해시.txt.
"""
import argparse, hashlib, json, os, statistics, subprocess, sys, tempfile, time, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
모듈들 = ["qwen2Q8", "qwen2Q8_7b", "qwen2Q4_7b", "qwen2Q4_5120x40x8x13824x152064",
       "qwen2K_3584x28x4x18944x152064", "qwen2K_5120x40x8x13824x152064"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geulpu")
    ap.add_argument("--뒷단", default=os.path.join(ROOT, "build", "자체PTX.exe"))
    ap.add_argument("--횟수", type=int, default=1)
    ap.add_argument("--출력")
    a = ap.parse_args()
    a.뒷단 = os.path.abspath(a.뒷단)
    기대 = {}
    for 줄 in open(os.path.join(a.geulpu, "시험", "모듈해시.txt"), encoding="utf-8"):
        칸 = [x.strip() for x in 줄.split("|")]
        if len(칸) >= 4 and 칸[0] in 모듈들:
            기대[칸[0]] = 칸[3]
    tmp = tempfile.mkdtemp(prefix="geul_ptx_")
    뒷단해시 = hashlib.sha256(open(a.뒷단, "rb").read()).hexdigest()
    결과 = {"뒷단_sha256": 뒷단해시, "모듈": {}}
    합 = 0.0
    모두같음 = True
    for m in 모듈들:
        gl = os.path.join(a.geulpu, "빌드", "글", m + ".gl")
        ptx = os.path.join(tmp, m + ".ptx")
        시간 = []
        for _ in range(a.횟수):
            t0 = time.perf_counter()
            r = subprocess.run([a.뒷단, gl, "-o", ptx], capture_output=True)
            시간.append(time.perf_counter() - t0)
            if r.returncode != 0:
                sys.exit(f"{m}: 뒷단 실패 {r.returncode}\n{r.stdout.decode('utf-8', 'replace')[-500:]}")
        h = hashlib.sha256(open(ptx, "rb").read()).hexdigest()
        같음 = h == 기대.get(m)
        모두같음 = 모두같음 and 같음
        t = statistics.median(시간)
        합 += t
        결과["모듈"][m] = {"초": t, "모두": 시간, "PTX_sha256": h, "기록과_같음": 같음}
        print(f"{m:34s} {t:7.2f} 초  PTX {'같음' if 같음 else '다름!'}", flush=True)
    결과["합_초"] = 합
    결과["모두_같음"] = 모두같음
    print(f"합 {합:.2f} 초 · 모두 같음 {모두같음} · 뒷단 {뒷단해시[:16]}…")
    if a.출력:
        json.dump(결과, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
