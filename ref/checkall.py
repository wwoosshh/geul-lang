"""개발용: 모든 spec-tests 에 --check 를 돌려 결과를 요약한다."""
import subprocess, sys, os, glob, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = bad = 0
for d in sorted(glob.glob(os.path.join(root, 'spec-tests', '*', '*'))):
    main = os.path.join(d, 'main.gl')
    if not os.path.exists(main): continue
    neg = os.path.exists(os.path.join(d, 'expect.errors'))
    r = subprocess.run([sys.executable, os.path.join(root, 'ref', 'geulc.py'), '--check', main], capture_output=True)
    out = (r.stdout + r.stderr).decode('utf-8', 'replace').strip()
    last = out.splitlines()[-1] if out else ''
    name = os.path.relpath(d, os.path.join(root, 'spec-tests'))
    if neg:
        wanted = [l for l in open(os.path.join(d, 'expect.errors'), encoding='utf-8').read().splitlines() if l.strip()]
        if r.returncode == 1 and all(w in out for w in wanted):
            ok += 1
        else:
            bad += 1; print(f'NEG-FAIL {name} rc={r.returncode} want={wanted} :: {last[:160]}')
    else:
        if r.returncode == 0:
            ok += 1
        else:
            bad += 1; print(f'FAIL {name} rc={r.returncode} :: {last[:200]}')
print(f'check ok={ok} bad={bad}')
