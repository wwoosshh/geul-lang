"""ncu 가 한글 경로를 못 다뤄서 두는 ASCII 이름의 얇은 실행기. 인자: ROOT 의 UTF-8 16진수, 그다음은 프로파일대상.py 의 인자 그대로.
기본 파이썬(ASCII 경로)으로 띄울 때를 위해 저장소 venv 의 site-packages 를 뒤에 붙인다."""
import sys, os, runpy
ROOT = bytes.fromhex(sys.argv[1]).decode("utf-8")
sp = os.path.join(ROOT, "build", "감사venv", "Lib", "site-packages")
if os.path.isdir(sp) and sp not in sys.path:
    sys.path.append(sp)
here = os.path.dirname(os.path.abspath(__file__))
sys.argv = [os.path.join(here, "프로파일대상.py"), ROOT] + sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
