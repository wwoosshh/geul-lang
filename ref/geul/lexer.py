"""렉서 (명세 2.1). 심볼 테이블 없음. 한글 단어는 통째로 WORD 토큰이다."""
from dataclasses import dataclass
from .diagnostics import CompileError, Pos

KEYWORDS = {"결과", "시도", "혹은", 
    "정수", "긴정수", "중간정수", "짧은정수", "작은정수", "부호없는", "실수", "짧은실수", "문자", "문자열", "참거짓", "공허",
    "참조", "참", "거짓", "없음",
    "포함", "외부", "정적", "상수", "별칭", "묶음", "나열", "합침",
    "반환", "이면", "아니면", "동안", "반복", "반복하기", "갈래", "경우", "기본", "탈출", "계속",
    "그리고", "또는", "아닌", "크기", "시작하기",
}
# 접사 (명세 2.4). 인자 위치에서 단어 끝에서 가장 긴 것을 뗀다.
PARTICLES = ["에서", "으로", "보다", "을", "를", "에", "로", "와", "과", "이", "가", "은", "는", "의"]
PARTICLE_SET = set(PARTICLES)
ROLE_OF = {
    "을": "대상", "를": "대상", "에": "목적지", "에서": "출처", "로": "수단", "으로": "수단",
    "와": "동반", "과": "동반", "보다": "비교", "이": "주어", "가": "주어", "은": "주제", "는": "주제", "의": "의",
}

SYMBOLS = [
    "<<=", ">>=", "...", "->", "<=", ">=", "==", "!=", "<<", ">>", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
    "(", ")", "[", "]", "{", "}", ",", ":", "&", "+", "-", "*", "/", "%", "<", ">", "^", "|", "~", "?", "=", "→",
]

# 토큰 종류
WORD, IDENT, KEYWORD, PARTICLE, INT, FLOAT, CHAR, STRING, SYM, END, EOF = (
    "단어", "식별자", "키워드", "접사", "정수리터럴", "실수리터럴", "문자리터럴", "문자열리터럴", "기호", "종결", "끝")


@dataclass
class Token:
    kind: str
    text: str
    pos: Pos
    value: object = None  # 리터럴 값

    def __repr__(self):
        return f"{self.kind}({self.text!r})"


def is_hangul(ch):
    """완성형 음절과 호환 자모. 결합형 자모(NFD)는 이름 글자가 아니다 — 명세 2.1."""
    o = ord(ch)
    return 0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F


def is_conjoining_jamo(ch):
    o = ord(ch)
    return 0x1100 <= o <= 0x11FF or 0xA960 <= o <= 0xA97F or 0xD7B0 <= o <= 0xD7FF


def is_latin_start(ch):
    return ch == "_" or ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def is_name_char(ch):
    return is_hangul(ch) or is_latin_start(ch) or ch.isdigit()


def object_particle(word):
    """낱말 뒤에 붙일 목적격 조사: 받침이 있으면 '을', 없으면 '를' (한글이 아니면 '를')."""
    ch = word[-1] if word else ""
    if "\uac00" <= ch <= "\ud7a3" and (ord(ch) - 0xAC00) % 28 != 0:
        return "을"
    return "를"


def split_particle(word):
    """단어 끝에서 가장 긴 접사를 뗀다. (어근, 접사) 또는 (단어, None)."""
    for p in sorted(PARTICLES, key=len, reverse=True):
        if word.endswith(p) and len(word) > len(p):
            return word[: -len(p)], p
    return word, None


class Lexer:
    def __init__(self, text, filename):
        self.text = text
        self.file = filename
        self.i = 0
        self.line = 1
        self.col = 1
        self.tokens = []

    def pos(self):
        return Pos(self.file, self.line, self.col)

    def peek(self, k=0):
        j = self.i + k
        return self.text[j] if j < len(self.text) else ""

    def advance(self, n=1):
        for _ in range(n):
            if self.i < len(self.text):
                if self.text[self.i] == "\n":
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
                self.i += 1

    def error(self, pos, msg):
        raise CompileError(pos, msg)

    def tokenize(self):
        while True:
            self.skip_space_and_comments()
            if self.i >= len(self.text):
                self.tokens.append(Token(EOF, "", self.pos()))
                return self.tokens
            ch = self.peek()
            p = self.pos()
            if ch.isdigit():
                self.lex_number(p)
            elif is_conjoining_jamo(ch):
                self.error(p, "한글이 NFC 로 정규화되어 있지 않습니다 (결합형 자모) — 소스를 NFC 로 저장하세요")
            elif is_hangul(ch) or is_latin_start(ch):
                self.lex_word(p)
            elif ch == '"':
                self.lex_string(p)
            elif ch == "'":
                self.lex_char(p)
            elif ch == ".":
                nxt = self.peek(1)
                if nxt == "" or nxt in " \t\n\r})":
                    self.advance()
                    self.tokens.append(Token(END, ".", p))
                elif nxt == "." and self.peek(2) == ".":
                    self.advance(3)
                    self.tokens.append(Token(SYM, "...", p))
                else:
                    self.error(p, "'.' 뒤에는 공백, 줄바꿈, '}' 또는 ')'가 와야 합니다")
            else:
                self.lex_symbol(p)

    def skip_space_and_comments(self):
        while self.i < len(self.text):
            ch = self.peek()
            if ch in " \t\n\r":
                self.advance()
            elif ch == "(" and self.peek(1) == "*":
                self.skip_comment()
            else:
                return

    def skip_comment(self):
        start = self.pos()
        depth = 0
        while self.i < len(self.text):
            if self.peek() == "(" and self.peek(1) == "*":
                depth += 1
                self.advance(2)
            elif self.peek() == "*" and self.peek(1) == ")":
                depth -= 1
                self.advance(2)
                if depth == 0:
                    return
            else:
                self.advance()
        self.error(start, "주석이 닫히지 않았습니다")

    def lex_number(self, p):
        start = self.i
        if self.peek() == "0" and self.peek(1) in "xX":
            self.advance(2)
            digits = ""
            while self.peek() and (self.peek().isdigit() or self.peek().lower() in "abcdef"):
                digits += self.peek()
                self.advance()
            if not digits:
                self.error(p, "16진 리터럴에 숫자가 없습니다")
            self.tokens.append(Token(INT, self.text[start:self.i], p, int(digits, 16)))
            return
        digits = ""
        while self.peek().isdigit() or self.peek() == "_":
            if self.peek() == "_":
                if not self.peek(1).isdigit() or digits.endswith("_"):
                    self.error(p, "정수 리터럴의 밑줄은 숫자 사이에만 올 수 있습니다")
            digits += self.peek()
            self.advance()
        is_float = False
        if self.peek() == "." and self.peek(1).isdigit():
            is_float = True
            self.advance()
            while self.peek().isdigit():
                digits += self.peek()
                self.advance()
        # 지수: e[+-]숫자 — 소수부가 없어도 실수 (1e22)
        if self.peek() in "eE" and (self.peek(1).isdigit() or (self.peek(1) in "+-" and self.peek(2).isdigit())):
            is_float = True
            self.advance()
            if self.peek() in "+-":
                self.advance()
            while self.peek().isdigit():
                self.advance()
        text = self.text[start:self.i]
        if is_float:
            self.tokens.append(Token(FLOAT, text, p, float(text.replace("_", ""))))
        else:
            self.tokens.append(Token(INT, text, p, int(digits.replace("_", ""))))

    def lex_word(self, p):
        start = self.i
        latin_start = is_latin_start(self.peek())
        has_hangul = False
        while self.peek() and is_name_char(self.peek()):
            if is_hangul(self.peek()):
                has_hangul = True
            self.advance()
        text = self.text[start:self.i]
        if latin_start and not has_hangul:
            self.tokens.append(Token(IDENT, text, p))
        elif text in KEYWORDS:
            self.tokens.append(Token(KEYWORD, text, p))
        elif text in PARTICLE_SET:
            self.tokens.append(Token(PARTICLE, text, p))
        else:
            self.tokens.append(Token(WORD, text, p))

    ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "{": "{", "}": "}", "'": "'"}

    def lex_string(self, p):
        self.advance()
        out = []
        raw = []
        while True:
            ch = self.peek()
            if ch == "" or ch == "\n":
                self.error(p, "문자열이 닫히지 않았습니다")
            if ch == '"':
                self.advance()
                break
            if ch == "\\":
                e = self.peek(1)
                if e not in self.ESCAPES:
                    self.error(self.pos(), f"알 수 없는 이스케이프 '\\{e}'")
                out.append(self.ESCAPES[e])
                raw.append("\\" + e)
                self.advance(2)
            else:
                out.append(ch)
                raw.append(ch)
                self.advance()
        self.tokens.append(Token(STRING, '"' + "".join(raw) + '"', p, "".join(out)))

    def lex_char(self, p):
        self.advance()
        ch = self.peek()
        if ch == "\\":
            e = self.peek(1)
            if e not in self.ESCAPES:
                self.error(p, f"알 수 없는 이스케이프 '\\{e}'")
            value = self.ESCAPES[e]
            self.advance(2)
        else:
            if ch == "" or ch == "'":
                self.error(p, "문자 리터럴이 비어 있습니다")
            value = ch
            self.advance()
        if self.peek() != "'":
            self.error(p, "문자 리터럴이 닫히지 않았습니다")
        self.advance()
        if ord(value) > 127:
            self.error(p, "문자 리터럴은 코드포인트 127 이하만 허용됩니다 (한글은 문자열로)")
        self.tokens.append(Token(CHAR, f"'{value}'", p, ord(value)))

    def lex_symbol(self, p):
        for s in SYMBOLS:
            if self.text.startswith(s, self.i):
                self.advance(len(s))
                if s == "→":
                    s = "->"
                self.tokens.append(Token(SYM, s, p))
                return
        self.error(p, f"알 수 없는 문자 '{self.peek()}'")


def tokenize(text, filename):
    return Lexer(text, filename).tokenize()
