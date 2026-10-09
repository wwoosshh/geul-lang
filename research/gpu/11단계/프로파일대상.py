"""ncu 가 볼 커널만 고른다: 실제 프롬프트를 그대로 한 번 다시 띄우면서 고른 층의 실행만 cuProfilerStart/Stop 사이에 둔다.
ncu 는 --profile-from-start off 로 그 사이만 잰다. 값은 엔진이 내는 것과 같은 데이터 위에서 돈다(그래프 없이 같은 차례로 다시 띄움).
인자: ROOT [크기=XL] [형식=q8_0] [길이=1024] [층=20] [보기=0]  — 보기=1 이면 계획의 차례와 이름만 찍고 끝낸다."""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import os, ctypes, time
ROOT = sys.argv[1]
크기 = sys.argv[2] if len(sys.argv) > 2 else "XL"
fmt = sys.argv[3] if len(sys.argv) > 3 else "q8_0"
n = int(sys.argv[4]) if len(sys.argv) > 4 else 1024
층 = int(sys.argv[5]) if len(sys.argv) > 5 else 20
보기 = len(sys.argv) > 6 and sys.argv[6] == "1"
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "3단계"))
sys.path.insert(0, os.path.join(ROOT, "research", "gpu", "5단계"))
import 글gpt2 as G
import gguf읽기 as GR
m = G.글GPT2(GR.gpt2정수(os.path.join(ROOT, "build", f"gpt2-{fmt}.gguf" if 크기 == "small" else f"gpt2-xl-{fmt}.gguf")),
             KV형식="정수", 최대문장=1, 자리수=2)
cu = m.dr.cu
tk = G.토크나이저(os.path.join(ROOT, "build", "gpt2" if 크기 == "small" else "gpt2-xl"))
글 = ("In a shocking finding, scientists discovered a herd of unicorns living in a remote, previously unexplored valley in the "
     "Andes Mountains. Even more surprising to the researchers was the fact that the unicorns spoke perfect English.")
긴 = (tk.나누기(글) * 40)[:n]
이름 = {}
for k, v in m.k.items():
    이름[v.value] = k
for (판, epi), v in m.선형.items():
    이름[v.value] = f"{판}{epi}"
for 판, v in m.로짓선형.items():
    이름[v.value] = f"로짓{판}"

m.토큰넣기(긴)
for _ in range(20):                      # 데우기 — 계획 · 그래프를 만들고 GPU 를 높은 클럭으로
    m.계산(1, n, 0, "끝")
m.dr.맞추기()
pos, tok, out, L = m._계획[(1, n, "끝")]
names = [이름.get(x.fn.value, "?") for x in L]
# 층의 시작: 층마다 한 번 나오는 c_attn 타일(끝 계산 _KV정수) 바로 앞의 층정규화
qkv = [i for i, s in enumerate(names) if s.endswith("_KV정수")]
층수 = len(qkv)
시작 = qkv[층] - 1
끝 = qkv[층 + 1] - 1 if 층 + 1 < 층수 else len(L)
if 보기:
    for i, (x, s) in enumerate(zip(L, names)):
        표 = "*" if 시작 <= i < 끝 else " "
        print(f"{표}{i:4d} {s:28s} grid {tuple(x.grid)} block {tuple(x.block)}  _G{s.encode('utf-8').hex() if s != '?' else ''}")
    print(f"층 {층수} 개, 고른 층 {층}: 실행 {시작} ~ {끝 - 1}")
    sys.exit(0)
run = lambda x: cu.cuLaunchKernel(x.fn, x.grid[0], x.grid[1], 1, x.block[0], x.block[1], 1, 0, None, x.args, None)
for i, x in enumerate(L):
    if i == 시작:
        m.dr.맞추기()
        m.dr.확인(cu.cuProfilerStart())
    m.dr.확인(run(x))
    if i == 끝 - 1:
        m.dr.맞추기()
        m.dr.확인(cu.cuProfilerStop())
m.dr.맞추기()
print(f"{크기} {fmt} {n}: 층 {층} 의 실행 {끝 - 시작} 개를 구간에 넣었다 — " + ", ".join(names[시작:끝]))
