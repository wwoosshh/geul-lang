"""컴파일러 자신의 속도를 여러 언어 · 여러 컴파일러와 견준다.

    python -I -X utf8 research/cpu/언어컴파일견주기.py [--횟수 7] [--합성 2048 8192] [--코어 P|E|없음] [--출력 <json>] [--자기횟수 15]
        [--zig <exe>] [--gcc <exe>] [--tcc <exe>] [--rustc <exe>] [--go <exe>] [--javac <exe>] [--java <exe>]

세 가지를 잰다(모두 프로세스 전체 벽시계 시간, 차례를 돌려 가며 번갈아 — 가운데 값):
1. 짝 일곱(빈 프로그램 + 여섯 짝)을 각 컴파일러로 — 작은 프로그램이라 대부분 컴파일러를 띄우는 값이다.
2. 합성 프로그램 — 같은 꼴의 함수 N 개(반복 · 조건 · 다음 함수 부름, 64 개마다 사슬을 끊는다)를 언어마다 같은 뜻으로 낸다.
   모두 같은 출력을 내는지 한 번 돌려 본다. 컴파일러가 코드 양에 따라 어떻게 늘어나는지 본다.
3. 글 컴파일러가 자기 자신(self/컴파일러.gl — 표준 라이브러리까지)을 컴파일하는 시간.
캐시를 피하려고 회차마다 원본 맨 앞에 회차 번호 주석을 단 새 사본을 컴파일한다(zig 의 캐시 · Go 의 빌드 캐시가 같은 원본을 건너뛰지 않게 —
Go 의 표준 라이브러리 꾸러미는 데운 캐시에서 온다).
"""
import argparse, json, os, shutil, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from 언어견주기 import BENCH, cpu_name, pin, run, source, which  # noqa: E402

CONFIGS = [
    ("글", "geul", "geulc", []),
    ("C clang -O0", "c", "zig", ["-O0"]),
    ("C clang -O2", "c", "zig", ["-O2", "-ffp-contract=off"]),
    ("C gcc -O0", "c", "gcc", ["-O0"]),
    ("C gcc -O2", "c", "gcc", ["-O2", "-ffp-contract=off"]),
    ("C tcc", "c", "tcc", []),
    ("Rust -O0", "rust", "rustc", ["-C", "opt-level=0"]),
    ("Rust -O3", "rust", "rustc", ["-C", "opt-level=3"]),
    ("Go", "go", "go", []),
    ("Java(javac)", "java", "javac", []),
]
COMMENT = {"geul": "(* 회차 {} *)\n", "c": "/* run {} */\n", "rust": "// run {}\n", "go": "// run {}\n", "java": "// run {}\n"}
EXT = {"geul": ".gl", "c": ".c", "rust": ".rs", "go": ".go", "java": ".java"}


def synth(lang, n):
    """같은 꼴의 함수 n 개(n 은 64 의 배수)와 사슬 머리를 부르는 시작 함수."""
    L = []
    if lang == "c":
        L += ["#include <stdio.h>", "#include <stdint.h>"]
    if lang == "go":
        L += ["package main", "", 'import "fmt"']
    if lang == "java":
        L += ["public class Syn {"]
    for k in range(n):
        last = k % 64 == 0
        if lang == "geul":
            L += [f"[정수 x를 함수{k}]는 -> 정수 {{", "    정수 s = x.", "    반복 (정수 i는 0부터 8 전까지) {",
                  "        (s & 1) == 1이면 { s = s * 3 + i. }", f"        아니면 {{ s = s / 2 + {k}. }}", "    }",
                  "    반환 s." if last else f"    반환 s + 함수{k - 1}(s & 255).", "}"]
        elif lang == "c":
            L += [f"static int64_t f{k}(int64_t x) {{", "    int64_t s = x;", "    for (int64_t i = 0; i < 8; i += 1) {",
                  "        if ((s & 1) == 1) { s = s * 3 + i; }", f"        else {{ s = s / 2 + {k}; }}", "    }",
                  "    return s;" if last else f"    return s + f{k - 1}(s & 255);", "}"]
        elif lang == "rust":
            L += [f"fn f{k}(x: i64) -> i64 {{", "    let mut s = x;", "    let mut i: i64 = 0;", "    while i < 8 {",
                  "        if (s & 1) == 1 { s = s * 3 + i; }", f"        else {{ s = s / 2 + {k}; }}", "        i += 1;", "    }",
                  "    s" if last else f"    s + f{k - 1}(s & 255)", "}"]
        elif lang == "go":
            L += [f"func f{k}(x int64) int64 {{", "\ts := x", "\tfor i := int64(0); i < 8; i += 1 {",
                  "\t\tif (s & 1) == 1 {", "\t\t\ts = s*3 + i", "\t\t} else {", f"\t\t\ts = s/2 + {k}", "\t\t}", "\t}",
                  "\treturn s" if last else f"\treturn s + f{k - 1}(s&255)", "}"]
        else:
            L += [f"    static long f{k}(long x) {{", "        long s = x;", "        for (long i = 0; i < 8; i += 1) {",
                  "            if ((s & 1) == 1) { s = s * 3 + i; }", f"            else {{ s = s / 2 + {k}; }}", "        }",
                  "        return s;" if last else f"        return s + f{k - 1}(s & 255);", "    }"]
    heads = [64 * j + 63 for j in range(n // 64)]
    if lang == "geul":
        L += ["[시작하기]는 -> 정수 {", "    정수 합 = 0."] + [f"    합 = 합 + 함수{h}(7)." for h in heads] + ['    "{합}\\n"을 쓰다.', "    반환 0.", "}"]
    elif lang == "c":
        L += ["int main(void) {", "    int64_t sum = 0;"] + [f"    sum = sum + f{h}(7);" for h in heads] + ['    printf("%lld\\n", (long long)sum);', "    return 0;", "}"]
    elif lang == "rust":
        L += ["fn main() {", "    let mut sum: i64 = 0;"] + [f"    sum = sum + f{h}(7);" for h in heads] + ['    println!("{}", sum);', "}"]
    elif lang == "go":
        L += ["func main() {", "\tvar sum int64 = 0"] + [f"\tsum = sum + f{h}(7)" for h in heads] + ["\tfmt.Println(sum)", "}"]
    else:
        L += ["    public static void main(String[] args) {", "        long sum = 0;"] + [f"        sum = sum + f{h}(7);" for h in heads] + \
             ['        System.out.print(sum + "\\n");', "    }", "}"]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    for t in ("zig", "gcc", "tcc", "rustc", "go", "javac", "java"):
        ap.add_argument("--" + t)
    ap.add_argument("--횟수", type=int, default=7)
    ap.add_argument("--합성", type=int, nargs="*", default=[2048, 8192])
    ap.add_argument("--합성횟수", type=int, default=5)
    ap.add_argument("--자기횟수", type=int, default=15)
    ap.add_argument("--만", nargs="*", default=BENCH)
    ap.add_argument("--코어", default="P", choices=["P", "E", "없음"])
    ap.add_argument("--출력", default=os.path.join(HERE, "언어컴파일결과.json"))
    a = ap.parse_args()
    tools = {"geulc": os.path.join(ROOT, "build", "self_컴파일러.exe")}
    for t in ("zig", "gcc", "tcc", "rustc", "go", "javac", "java"):
        tools[t] = which(getattr(a, t), t)
    if any(not tools[c[2]] for c in CONFIGS):
        sys.exit(f"도구를 찾지 못했다: {[c[2] for c in CONFIGS if not tools[c[2]]]}")
    cpus = pin(a.코어)
    tmp = tempfile.mkdtemp(prefix="geul_cc_")
    genv = dict(os.environ, GEUL_ROOT=ROOT)
    goenv = dict(os.environ, GOTOOLCHAIN="local", GOFLAGS="", GOCACHE=os.path.join(tmp, "gocache"), GOPATH=os.path.join(tmp, "gopath"),
                 GOROOT=os.path.dirname(os.path.dirname(tools["go"])))
    counter = [0]

    def compile_once(cfg, text, base):
        """새 사본(회차 주석)을 컴파일 — (초, 종료 코드, 출력 exe 또는 클래스 폴더)"""
        name, lang, tool, flags = cfg
        counter[0] += 1
        d = os.path.join(tmp, f"c{counter[0]}")
        os.makedirs(d)
        src = os.path.join(d, base + EXT[lang])
        with open(src, "w", encoding="utf-8", newline="\n") as f:
            f.write(COMMENT[lang].format(counter[0]) + text)
        exe = os.path.join(d, "o.exe")
        if lang == "geul":
            cmd, env = [tools["geulc"], src, "-o", exe], genv
        elif lang == "c":
            cmd, env = ([tools["zig"], "cc"] if tool == "zig" else [tools[tool]]) + flags + ["-o", exe, src], None
        elif lang == "rust":
            cmd, env = [tools["rustc"], *flags, src, "-o", exe], None
        elif lang == "go":
            cmd, env = [tools["go"], "build", *flags, "-o", exe, src], goenv
        else:
            cmd, env = [tools["javac"], "-encoding", "UTF-8", "-d", d, src], None
        t0 = time.perf_counter_ns()
        r = subprocess.run(cmd, capture_output=True, env=env, cwd=d, stdin=subprocess.DEVNULL)
        dt = (time.perf_counter_ns() - t0) / 1e9
        if r.returncode != 0:
            sys.exit(f"컴파일 실패 {name} {base}: {' '.join(cmd)}\n{(r.stdout + r.stderr).decode('utf-8', 'replace')[:2000]}")
        return dt, (d if lang == "java" else exe)

    def measure(inputs, n):
        """inputs: [(cfg, text, base)] — 데운 뒤 n 번 차례를 돌려 가며. {cfg 이름: [초]}"""
        for cfg, text, base in inputs:
            compile_once(cfg, text, base)
        ts = {cfg[0]: [] for cfg, _, _ in inputs}
        for r in range(n):
            order = inputs[r % len(inputs):] + inputs[:r % len(inputs)]
            for cfg, text, base in order:
                ts[cfg[0]].append(compile_once(cfg, text, base)[0])
        return ts

    def summ(ts):
        return {k: {"가운데": statistics.median(v), "최소": min(v), "최대": max(v), "모두": v} for k, v in ts.items()}

    result = {"정보": {"시각": time.strftime("%Y-%m-%d %H:%M"), "cpu": cpu_name(), "묶은 논리 CPU": cpus, "횟수": a.횟수}, "짝": {}, "합성": {}}

    # 1. 짝
    for b in a.만:
        inputs = []
        for cfg in CONFIGS:
            src = source(b, cfg[1])
            base = os.path.splitext(os.path.basename(src))[0]
            inputs.append((cfg, open(src, encoding="utf-8").read(), base))
        s = summ(measure(inputs, a.횟수))
        result["짝"][b] = s
        print(f"{b:7s} " + " | ".join(f"{k} {v['가운데'] * 1000:7.0f}ms" for k, v in s.items()), flush=True)
        json.dump(result, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 2. 합성
    for n in a.합성:
        texts = {lang: synth(lang, n) for lang in EXT}
        outs = {}
        for cfg in CONFIGS:                                   # 한 번 컴파일해 돌려 본다 — 모두 같은 출력이어야
            _, out = compile_once(cfg, texts[cfg[1]], "Syn" if cfg[1] == "java" else "syn")
            cmd = [tools["java"], "-cp", out, "Syn"] if cfg[1] == "java" else [out]
            rc, o, e = run(cmd)
            outs[cfg[0]] = o.strip() if rc == 0 else f"실패 {rc} {e[:200]}"
        if len(set(outs.values())) != 1:
            sys.exit(f"합성 {n}: 출력이 다르다 {outs}")
        lines = {lang: texts[lang].count("\n") for lang in EXT}
        inputs = [(cfg, texts[cfg[1]], "Syn" if cfg[1] == "java" else "syn") for cfg in CONFIGS]
        s = summ(measure(inputs, a.합성횟수))
        result["합성"][str(n)] = {"줄": lines, "출력": outs["글"], "시간": s}
        print(f"합성 {n} 함수 (글 {lines['geul']}줄) " + " | ".join(f"{k} {v['가운데']:6.2f}s" for k, v in s.items()), flush=True)
        json.dump(result, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 3. 자기 자신
    selfsrc = os.path.join(ROOT, "self", "컴파일러.gl")
    out = os.path.join(tmp, "self.exe")
    ts = []
    for r in range(a.자기횟수 + 1):
        t0 = time.perf_counter_ns()
        subprocess.run([tools["geulc"], selfsrc, "-o", out], check=True, capture_output=True, env=genv, cwd=ROOT)
        if r:
            ts.append((time.perf_counter_ns() - t0) / 1e9)
    result["자기 자신"] = {"가운데": statistics.median(ts), "최소": min(ts), "최대": max(ts), "모두": ts}
    print(f"자기 자신(self/컴파일러.gl): {statistics.median(ts) * 1000:.0f} ms (최소 {min(ts) * 1000:.0f} · 최대 {max(ts) * 1000:.0f})")
    json.dump(result, open(a.출력, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
