"""글 (geul) — 한국어 문법(SOV·조사)으로 쓰는 자체호스팅 시스템 언어의 컴파일러 (Windows x64).

이 꾸러미는 GitHub 릴리스와 바이트가 같은 geulc.exe 와 표준 라이브러리(표준/)를 담는다 (D-47).
`geulc` 명령과 `python -m geul` 이 그것을 부른다 — __main__.py.
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("geul")       # 판 번호는 VERSION 한 곳에서 (헌장) — 휠 메타데이터를 읽는다
except PackageNotFoundError:
    __version__ = "0+unknown"
