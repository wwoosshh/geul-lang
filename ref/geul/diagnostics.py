"""진단. D-03: 범주는 오류 하나. 위치는 항상 포함. 종료코드 0/1/2/3."""
from dataclasses import dataclass

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_INTERNAL_ERROR = 2
EXIT_USAGE_ERROR = 3


@dataclass(frozen=True)
class Pos:
    file: str
    line: int
    col: int

    def __str__(self):
        return f"{self.file}:{self.line}:{self.col}"


class CompileError(Exception):
    """사용자 오류. 메시지는 spec-tests 의 expect.errors 가 고정한다."""

    def __init__(self, pos, message):
        super().__init__(f"{pos}: 오류: {message}")
        self.pos = pos
        self.message = message


class InternalError(Exception):
    """컴파일러 불변식 위반. 종료코드 2."""


class Diagnostics:
    def __init__(self):
        self.errors = []

    def error(self, pos, message):
        self.errors.append(CompileError(pos, message))

    @property
    def count(self):
        return len(self.errors)

    def render(self):
        return "\n".join(str(e) for e in self.errors)
