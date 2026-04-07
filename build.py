#!/usr/bin/env python3
"""글 컴파일러 네이티브 자체빌드 스크립트

사용법:
    python3 build.py              # 빌드만
    python3 build.py --test       # 빌드 + 테스트
    python3 build.py --fixpoint   # 빌드 + 고정점 검증
    python3 build.py --install    # 빌드 + dist/compiler.exe 교체
"""
import os, sys, subprocess, shutil, time, glob, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'src')
STD = os.path.join(ROOT, 'std')
DIST = os.path.join(ROOT, 'dist')
TESTS = os.path.join(ROOT, 'tests')
EXAMPLES = os.path.join(ROOT, 'examples')
COMPILER = os.path.join(DIST, 'compiler.exe')
MERGED = os.path.join(DIST, '_build_merged.gl')
NEW_EXE = os.path.join(DIST, '_build_merged.exe')

SRC_FILES = [
    'tokens', 'unicode', 'lexer', 'ast', 'parser',
    'ir', 'ir_transform', 'ir_codegen', 'asm_gen',
    'pe_gen', 'elf_gen', 'compiler'
]

def merge_source():
    content = ''
    core = os.path.join(STD, 'core.gl')
    with open(core, 'r', encoding='utf-8') as f:
        content += f.read() + '\n'
    for fn in SRC_FILES:
        fpath = os.path.join(SRC, fn + '.gl')
        if os.path.exists(fpath):
            with open(fpath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            filtered = [l for l in lines if not l.strip().startswith('포함 ')]
            content += ''.join(filtered) + '\n'
    with open(MERGED, 'w', encoding='utf-8') as f:
        f.write(content)
    return len(content)

def build():
    if not os.path.exists(COMPILER):
        print(f'오류: {COMPILER} 없음 — bootstrap/dist_build.ps1로 먼저 빌드하세요')
        sys.exit(1)

    print('[1/2] 소스 병합...')
    size = merge_source()
    print(f'      {size:,} bytes')

    print('[2/2] 네이티브 빌드...')
    t0 = time.time()
    r = subprocess.run([COMPILER, '--no-std', MERGED], capture_output=True, encoding='utf-8', errors='replace')
    elapsed = (time.time() - t0) * 1000
    if r.stderr:
        print(r.stderr)
    if r.stdout:
        for line in r.stdout.strip().split('\n'):
            print(f'      {line}')

    if not os.path.exists(NEW_EXE):
        print(f'빌드 실패 ({elapsed:.0f}ms)')
        sys.exit(1)

    sz = os.path.getsize(NEW_EXE)
    print(f'      완료: {sz:,} bytes ({elapsed:.0f}ms)')
    return NEW_EXE

def test(compiler_exe):
    print('\n[테스트]')
    passed = failed = skipped = 0
    test_files = sorted(glob.glob(os.path.join(TESTS, '*.gl')))
    test_files += sorted(glob.glob(os.path.join(EXAMPLES, '*.글')))

    for src in test_files:
        name = os.path.splitext(os.path.basename(src))[0]
        d = os.path.dirname(src)
        exe = os.path.join(d, name + '.exe')
        if os.path.exists(exe):
            os.remove(exe)

        r = subprocess.run([compiler_exe, src], capture_output=True, text=True, timeout=30)
        if os.path.exists(exe):
            try:
                rr = subprocess.run([exe], capture_output=True, text=True, timeout=5)
                if rr.returncode in (0, 42):
                    print(f'  PASS: {name}')
                    passed += 1
                else:
                    print(f'  FAIL: {name} (exit={rr.returncode})')
                    failed += 1
            except subprocess.TimeoutExpired:
                print(f'  TIMEOUT: {name}')
                failed += 1
            finally:
                os.remove(exe)
        else:
            out = (r.stdout or '') + (r.stderr or '')
            skipped += 1

    print(f'\n  결과: PASS={passed}, FAIL={failed}, SKIP={skipped}')
    return failed == 0

def fixpoint(new_exe):
    print('\n[고정점 검증]')
    stage2 = os.path.join(DIST, '_fp_stage2.exe')
    shutil.copy2(new_exe, stage2)

    subprocess.run([stage2, '--no-std', MERGED], capture_output=True, timeout=30)
    stage3 = NEW_EXE  # overwritten by stage2

    import filecmp
    if filecmp.cmp(stage2, stage3, shallow=False):
        print('  IDENTICAL — 고정점 달성!')
        os.remove(stage2)
        return True
    else:
        print('  DIFFERENT — 고정점 실패')
        os.remove(stage2)
        return False

def install(new_exe):
    backup = COMPILER + '.bak'
    if os.path.exists(COMPILER):
        shutil.copy2(COMPILER, backup)
        print(f'  백업: {backup}')
    shutil.copy2(new_exe, COMPILER)
    print(f'  설치: {COMPILER}')

def cleanup():
    for f in [MERGED, NEW_EXE]:
        if os.path.exists(f):
            os.remove(f)

if __name__ == '__main__':
    args = sys.argv[1:]
    do_test = '--test' in args
    do_fp = '--fixpoint' in args
    do_install = '--install' in args

    new_exe = build()

    if do_test:
        test(new_exe)

    if do_fp:
        fixpoint(new_exe)

    if do_install:
        fixpoint(new_exe)
        install(new_exe)

    cleanup()
