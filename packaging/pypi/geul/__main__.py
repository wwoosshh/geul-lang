"""geulc 런처 (D-47): pip 가 만든 `geulc` 명령과 `python -m geul` 이 이 main 을 부른다.

꾸러미 안의 geulc.exe 를 인자 그대로 실행하고 종료 코드를 돌려준다. 표준 라이브러리는 꾸러미 안의
표준/ 을 쓰도록 GEUL_ROOT 를 정한다 — 바깥에 GEUL_ROOT 가 있어도 판이 맞는 이쪽이 이긴다.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if sys.platform != "win32":
        sys.stderr.write("geulc: 글 컴파일러는 Windows x64 실행 파일입니다 (만드는 실행 파일도 Windows x64)\n")
        return 3
    exe = os.path.join(HERE, "geulc.exe")
    env = dict(os.environ, GEUL_ROOT=HERE)
    try:
        return subprocess.call([exe] + sys.argv[1:], env=env)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
