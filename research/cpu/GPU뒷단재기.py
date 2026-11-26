"""GPU 컴파일러로서의 글 — GeulPU 의 커널 생성기 · PTX 뒷단 · SPIR-V 뒷단(모두 글로 쓴 CPU 프로그램)의 시간과 최대 메모리를 잰다.
같은 PTX 를 NVIDIA ptxas(PTX → SASS, C++ 로 쓴 산업용 최적화 어셈블러)가 받는 시간도 함께 잰다 — GPU 없이 된다.

    python -I -X utf8 research/cpu/GPU뒷단재기.py --판 <이름>=<bin 폴더> [--판 ...] --모듈 <커널 소스 .gl 폴더> --해시 <모듈해시.txt>
        [--이름 <모듈> ...] [--횟수 3] [--ptxas <exe> --ptxas대상 sm_89] [--코어 P|E|없음] [--출력 <json>]

- bin 폴더: GeulPU 의 빌드(커널생성.exe · ptx-backend.exe · spirv-backend.exe — 이 저장소의 컴파일러로 GeulPU 의 커널/ · 백엔드/ 를 빌드한 것).
- 모듈 폴더: 커널생성으로 만든 <모듈>.gl. 해시: GeulPU 의 시험/모듈해시.txt — 뒷단의 출력이 바이트까지 그 기록과 같아야 잰다.
- 판이 둘 이상이면 모듈마다 차례를 바꿔 가며 번갈아 --횟수 번 — 프로세스 전체 벽시계 시간의 가운데 값. MoE 모듈(CUDA 만)은 SPIR-V 가 없다.
- 최대 메모리는 프로세스의 PeakWorkingSetSize(윈도).
"""
import argparse, ctypes, hashlib, json, os, statistics, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from 언어견주기 import pin, cpu_name  # noqa: E402


class PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def timed(cmd, log):
    """(초, 최대 작업 집합 바이트, 종료 코드)"""
    with open(log, "wb") as f:
        t0 = time.perf_counter_ns()
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        p.wait()
        dt = (time.perf_counter_ns() - t0) / 1e9
    peak = 0
    if os.name == "nt":
        m = PMC()
        m.cb = ctypes.sizeof(PMC)
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(int(p._handle)), ctypes.byref(m), m.cb):
            peak = m.PeakWorkingSetSize
    return dt, peak, p.returncode


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--판", action="append", required=True, help="이름=bin 폴더")
    ap.add_argument("--모듈", required=True)
    ap.add_argument("--해시", required=True)
    ap.add_argument("--이름", nargs="*")
    ap.add_argument("--횟수", type=int, default=3)
    ap.add_argument("--ptxas")
    ap.add_argument("--ptxas대상", default="sm_89")
    ap.add_argument("--ptxas횟수", type=int, default=1)
    ap.add_argument("--뒷단만", action="store_true", help="ptxas 를 돌리지 않는다")
    ap.add_argument("--코어", default="P", choices=["P", "E", "없음"])
    ap.add_argument("--출력", default=os.path.join(HERE, "GPU뒷단결과.json"))
    a = ap.parse_args()
    판들 = [tuple(x.split("=", 1)) for x in a.판]
    표 = {}
    for 줄 in open(a.해시, encoding="utf-8"):
        if 줄.strip() and not 줄.startswith("#"):
            칸 = [x.strip() for x in 줄.split("|")]
            표[칸[0]] = {"인자": 칸[1], "gl": 칸[2], "ptx": 칸[3], "spv": 칸[4] if len(칸) > 4 else ""}
    이름들 = a.이름 or sorted(os.path.splitext(f)[0] for f in os.listdir(a.모듈) if f.endswith(".gl"))
    cpus = pin(a.코어)
    out = os.path.join(a.모듈, "_out")
    os.makedirs(out, exist_ok=True)
    결과 = {"정보": {"시각": time.strftime("%Y-%m-%d %H:%M"), "cpu": cpu_name(), "묶은 논리 CPU": cpus, "횟수": a.횟수,
                    "판": {n: {x: sha(os.path.join(d, x + ".exe"))[:16] for x in ("ptx-backend", "spirv-backend")} for n, d in 판들}},
            "모듈": {}}
    print(json.dumps(결과["정보"], ensure_ascii=False), flush=True)
    for 이름 in 이름들:
        gl = os.path.join(a.모듈, 이름 + ".gl")
        rec = 표.get(이름)
        if rec is None:
            sys.exit(f"{이름}: 해시 표에 없다")
        if sha(gl) != rec["gl"]:
            sys.exit(f"{이름}: 커널 소스가 기록과 다르다")
        일들 = [("PTX", "ptx-backend", ".ptx", rec["ptx"])]
        if "--MoE" not in rec["인자"].split():
            일들.append(("SPIR-V", "spirv-backend", ".spvs", rec["spv"]))
        m = {"소스 MB": os.path.getsize(gl) / 1e6}
        for 일, exe, ext, want in 일들:
            시간 = {n: [] for n, _ in 판들}
            최대 = {n: 0 for n, _ in 판들}
            크기 = 0
            for r in range(a.횟수):
                차례 = 판들[r % len(판들):] + 판들[:r % len(판들)]
                for n, d in 차례:
                    o = os.path.join(out, f"{이름}.{n}{ext}")
                    if os.path.exists(o):
                        os.remove(o)
                    dt, peak, rc = timed([os.path.join(d, exe + ".exe"), gl, "-o", o], os.path.join(out, f"{이름}.{n}.{일}.log"))
                    if rc != 0 or not os.path.exists(o):
                        sys.exit(f"{이름} {일} {n}: 실패(종료 {rc}) — {os.path.join(out, f'{이름}.{n}.{일}.log')}")
                    if sha(o) != want:
                        sys.exit(f"{이름} {일} {n}: 출력이 기록과 다르다")
                    크기 = os.path.getsize(o)
                    시간[n].append(dt)
                    최대[n] = max(최대[n], peak)
            m[일] = {"출력 MB": 크기 / 1e6, "판": {n: {"가운데": statistics.median(시간[n]), "모두": 시간[n], "최대메모리GB": 최대[n] / 1e9}
                                                  for n, _ in 판들}}
            print(f"{이름:48s} {일:6s} " + " | ".join(f"{n} {statistics.median(시간[n]):6.2f}s {최대[n] / 1e9:4.1f}GB" for n, _ in 판들), flush=True)
        if a.ptxas and not a.뒷단만:
            ptx = os.path.join(out, f"{이름}.{판들[-1][0]}.ptx")
            cubin = os.path.join(out, f"{이름}.cubin")
            ts, peak = [], 0
            for _ in range(a.ptxas횟수):
                dt, pk, rc = timed([a.ptxas, f"-arch={a.ptxas대상}", ptx, "-o", cubin], os.path.join(out, f"{이름}.ptxas.log"))
                if rc != 0:
                    sys.exit(f"{이름}: ptxas 실패 — {os.path.join(out, f'{이름}.ptxas.log')}")
                ts.append(dt)
                peak = max(peak, pk)
            m["ptxas"] = {"대상": a.ptxas대상, "가운데": statistics.median(ts), "모두": ts, "최대메모리GB": peak / 1e9,
                          "cubin MB": os.path.getsize(cubin) / 1e6}
            print(f"{이름:48s} ptxas  {statistics.median(ts):6.2f}s {peak / 1e9:4.1f}GB (→ {os.path.getsize(cubin) / 1e6:.1f} MB cubin)", flush=True)
        결과["모듈"][이름] = m
        json.dump(결과, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for 일 in ("PTX", "SPIR-V"):
        합 = {n: sum(v[일]["판"][n]["가운데"] for v in 결과["모듈"].values() if 일 in v) for n, _ in 판들}
        print(f"합 {일}: " + " | ".join(f"{n} {s:.2f}s" for n, s in 합.items()))
    if a.ptxas and not a.뒷단만:
        print(f"합 ptxas: {sum(v['ptxas']['가운데'] for v in 결과['모듈'].values()):.2f}s")
    json.dump(결과, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
