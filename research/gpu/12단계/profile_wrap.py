"""ncu 용 ASCII 실행기: 인자 ROOT 의 UTF-8 16진수, 스크립트 이름(이 폴더 안)의 UTF-8 16진수, 그다음은 스크립트의 인자(16진수면 h: 를 붙여).
스크립트는 sys.argv = [스크립트, ROOT, 인자…] 로 돈다. 기본 파이썬으로 띄울 때를 위해 venv 의 site-packages 를 뒤에 붙인다."""
import sys, os, runpy
ROOT = bytes.fromhex(sys.argv[1]).decode("utf-8")
name = bytes.fromhex(sys.argv[2]).decode("utf-8")
rest = [bytes.fromhex(a[2:]).decode("utf-8") if a.startswith("h:") else a for a in sys.argv[3:]]
sp = os.path.join(ROOT, "build", "감사venv", "Lib", "site-packages")
if os.path.isdir(sp) and sp not in sys.path:
    sys.path.append(sp)
here = os.path.dirname(os.path.abspath(__file__))
sys.argv = [os.path.join(here, name), ROOT] + rest
runpy.run_path(sys.argv[0], run_name="__main__")
