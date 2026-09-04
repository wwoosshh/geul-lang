#!/usr/bin/env python3
"""geulc — 글 2세대 참조 컴파일러 명령줄 (명세 6절)."""
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from geul.diagnostics import CompileError, InternalError, EXIT_OK, EXIT_USER_ERROR, EXIT_INTERNAL_ERROR, EXIT_USAGE_ERROR  # noqa: E402
from geul import driver  # noqa: E402

USAGE = """사용법: geulc <소스.gl> [-o <출력.exe>] [--check] [--dump-ir] [--version] [--help]

옵션:
  -o <파일>     출력 실행 파일 경로 (기본: 소스와 같은 이름의 .exe)
  --check       문법·의미 검사만 하고 출력을 만들지 않는다
  --창, --gui   콘솔 없이 뜨는 창 프로그램으로 만든다 (PE 서브시스템 2)
  --dump-ir     타입 IR 을 표준출력으로
  --dump-tokens 토큰 덤프 (docs/05-덤프-형식.md)
  --dump-ast    구문 트리 덤프 (파일 하나, 포함 파일의 타입 이름만 반영)
  --dump-calls  호출 색인: 정의와 호출부 (docs/05-덤프-형식.md)
  --dump-risky  바꿔 쓰기 위험: 역할 조사를 안 붙인 호출부
  --version     버전 표시
  --help        이 도움말
"""


def read_version():
    try:
        return open(os.path.join(HERE, "..", "VERSION"), encoding="utf-8").read().strip()
    except OSError:
        return "0.0.0"


def main(argv):
    src = None
    out = None
    check = False
    gui = False
    dump_ir = False
    dump = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--help":
            print(USAGE, end="")
            return EXIT_OK
        if a == "--version":
            print(f"글 참조 컴파일러 v{read_version()}")
            return EXIT_OK
        if a == "--check":
            check = True
        elif a in ("--창", "--gui"):
            gui = True
        elif a == "--dump-ir":
            dump_ir = True
        elif a == "--dump-tokens":
            dump = "tokens"
        elif a == "--dump-calls":
            dump = "calls"
        elif a == "--dump-risky":
            dump = "risky"
        elif a == "--dump-ast":
            dump = "ast"
        elif a == "-o":
            if i + 1 >= len(argv):
                print("사용법 오류: -o 뒤에 출력 파일이 필요합니다", file=sys.stderr)
                return EXIT_USAGE_ERROR
            out = argv[i + 1]
            i += 1
        elif a.startswith("-"):
            print(f"사용법 오류: 알 수 없는 옵션 '{a}'", file=sys.stderr)
            return EXIT_USAGE_ERROR
        else:
            if src is not None:
                print("사용법 오류: 소스 파일은 하나만 지정합니다", file=sys.stderr)
                return EXIT_USAGE_ERROR
            src = a
        i += 1
    if src is None:
        print(USAGE, end="", file=sys.stderr)
        return EXIT_USAGE_ERROR
    try:
        return driver.compile_file(src, out, check=check, dump_ir=dump_ir, std_dir=os.path.join(HERE, "..", "표준"), dump=dump, gui=gui)
    except CompileError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USER_ERROR
    except InternalError as e:
        print(f"내부 오류: {e}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
