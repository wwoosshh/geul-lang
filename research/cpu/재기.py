"""글(geul) 컴파일러가 낸 x86-64 와 C(zig cc — clang)의 속도를 같은 알고리즘 · 같은 입력으로 잰다.

    python -I -X utf8 research/cpu/재기.py [--zig <zig.exe>] [--횟수 7] [--출력 research/cpu/결과.json]

- 글: 이 저장소의 자체 컴파일러 build/self_컴파일러.exe (배포되는 geulc.exe 와 같은 바이트를 낸다).
- C: zig cc 세 가지 — -O0, -O2, -O2 에서 벡터화 끔(-fno-vectorize -fno-slp-vectorize). 실수 계산은 -ffp-contract=off
  (글은 소스가 곱해더하기 를 적을 때만 곱과 합을 합친다 — 같은 값을 내게).
- 원본은 ASCII 이름의 임시 폴더로 옮겨 빌드한다. 출력(한 줄)이 모든 빌드에서 같아야 잰다. sha256 은 파이썬 hashlib 과도 견준다.
- 재기: 빌드마다 한 번 데운 뒤, 차례를 돌려 가며 --횟수 번 — 프로세스 전체의 벽시계 시간(시작 포함)의 중앙값.
- GPU 재기와 함께 돌리지 않는다.
"""
import argparse, json, os, platform, shutil, statistics, subprocess, sys, tempfile, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BENCH = ["fib", "sieve", "bubble", "matmul", "sha256", "rope"]
C_VARIANTS = [("C -O0", ["-O0"]),
              ("C -O2", ["-O2", "-ffp-contract=off"]),
              ("C -O2 벡터화 끔", ["-O2", "-ffp-contract=off", "-fno-vectorize", "-fno-slp-vectorize"])]


def find_zig(given):
    if given:
        return given
    z = shutil.which("zig")
    if z:
        return z
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    for d, _dirs, files in os.walk(base):
        if "zig.exe" in files:
            return os.path.join(d, "zig.exe")
    sys.exit("zig 를 찾지 못했다 — --zig 로 준다")


def run(cmd, env=None, cwd=None):
    r = subprocess.run(cmd, capture_output=True, env=env, cwd=cwd)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def sha256_expected():
    import numpy as np
    i = np.arange(67108864, dtype=np.int64)
    b = ((i * 2654435761) >> 13) & 255
    return hashlib.sha256(b.astype(np.uint8).tobytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zig")
    ap.add_argument("--횟수", type=int, default=7)
    ap.add_argument("--출력", default=os.path.join(HERE, "결과.json"))
    ap.add_argument("--만", nargs="*", default=BENCH)
    a = ap.parse_args()
    zig = find_zig(a.zig)
    geulc = os.path.join(ROOT, "build", "self_컴파일러.exe")
    if not os.path.isfile(geulc):
        sys.exit(f"{geulc} 가 없다 — python ref/geulc.py self/컴파일러.gl -o build/self_컴파일러.exe")
    env = dict(os.environ, GEUL_ROOT=ROOT)
    tmp = tempfile.mkdtemp(prefix="geul_cpu_")
    info = {"zig": run([zig, "version"])[1].strip(), "geulc_sha256": hashlib.sha256(open(geulc, "rb").read()).hexdigest(),
            "cpu": platform.processor(), "python": sys.version.split()[0], "횟수": a.횟수, "시각": time.strftime("%Y-%m-%d %H:%M")}
    builds = {}
    for b in a.만:
        shutil.copy(os.path.join(HERE, b + ".gl"), os.path.join(tmp, b + ".gl"))
        shutil.copy(os.path.join(HERE, b + ".c"), os.path.join(tmp, b + ".c"))
        exe = os.path.join(tmp, f"{b}_geul.exe")
        rc, o, e = run([geulc, os.path.join(tmp, b + ".gl"), "-o", exe], env=env)
        if rc != 0:
            sys.exit(f"글 빌드 실패 {b}: {o}{e}")
        builds[b] = [("글", exe)]
        for k, (name, flags) in enumerate(C_VARIANTS):
            exe = os.path.join(tmp, f"{b}_c{k}.exe")
            rc, o, e = run([zig, "cc", *flags, "-o", exe, os.path.join(tmp, b + ".c")], cwd=tmp)
            if rc != 0:
                sys.exit(f"C 빌드 실패 {b} {name}: {o}{e}")
            builds[b].append((name, exe))
    결과 = {"정보": info, "재기": {}}
    for b in a.만:
        outs = {}
        for name, exe in builds[b]:
            rc, o, e = run([exe])
            if rc != 0:
                sys.exit(f"실행 실패 {b} {name}: {rc} {o}{e}")
            outs[name] = o.strip()
        if len(set(outs.values())) != 1:
            sys.exit(f"{b}: 출력이 다르다 {outs}")
        if b == "sha256":
            want = sha256_expected()
            if outs["글"] != want:
                sys.exit(f"sha256 이 hashlib 과 다르다: {outs['글']} / {want}")
        시간 = {name: [] for name, _ in builds[b]}
        for r in range(a.횟수):
            order = builds[b][r % len(builds[b]):] + builds[b][:r % len(builds[b])]
            for name, exe in order:
                t0 = time.perf_counter()
                subprocess.run([exe], capture_output=True)
                시간[name].append(time.perf_counter() - t0)
        중앙 = {name: statistics.median(v) for name, v in 시간.items()}
        결과["재기"][b] = {"출력": outs["글"], "중앙값": 중앙, "모두": 시간}
        g = 중앙["글"]
        print(f"{b:8s} 글 {g:7.3f} s | " + " | ".join(f"{n} {중앙[n]:7.3f} s (글 {g / 중앙[n]:5.2f}배)" for n, _ in C_VARIANTS), flush=True)
    json.dump(결과, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
