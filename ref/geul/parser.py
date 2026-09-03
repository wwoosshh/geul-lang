"""파서 (명세 3절). 단어 분리는 문법 위치가 결정한다 (명세 2.2)."""
from . import ast as A
from .diagnostics import CompileError
from .lexer import (WORD, IDENT, KEYWORD, PARTICLE, INT, FLOAT, CHAR, STRING, SYM, END, EOF,
                    split_particle, ROLE_OF, is_hangul)

BASE_TYPES = {"정수", "긴정수", "짧은정수", "작은정수", "실수", "짧은실수", "문자", "문자열", "참거짓", "공허"}
INT_TYPES = {"정수", "긴정수", "짧은정수", "작은정수"}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}
COMPARE_VERBS = {"크거나같": ">=", "작거나같": "<=", "크": ">", "작": "<", "같": "==", "다르": "!="}
BINARY_PREC = [
    ("또는",), ("그리고",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">="), ("<<", ">>"),
    ("+", "-"), ("*", "/", "%"),
]


def strip_verb_ending(word):
    """동사 위치의 단어: (어근, 어미). 어미는 다/고/서 중 하나."""
    if len(word) >= 2 and word[-1] in "다고서":
        return word[:-1], word[-1]
    return None, None


def verb_base(root):
    """어근에서 '하'를 뗀 기본형 (출력하 → 출력). 없으면 어근 그대로."""
    if root.endswith("하") and len(root) > 1:
        return root[:-1]
    return root


class Parser:
    def __init__(self, tokens, filename):
        self.toks = tokens
        self.file = filename
        self.i = 0
        self.limit = len(tokens)      # 식 파싱 상한 (배타)
        self.type_names = set()

    # ---------- 토큰 유틸 ----------
    def peek(self, k=0):
        j = self.i + k
        if j >= self.limit:
            return self.toks[min(self.limit, len(self.toks) - 1)] if j >= len(self.toks) else self.toks[j]
        return self.toks[j]

    def at_limit(self):
        return self.i >= self.limit

    def tok(self):
        return self.toks[self.i] if self.i < len(self.toks) else self.toks[-1]

    def next(self):
        t = self.tok()
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def error(self, pos, msg):
        raise CompileError(pos, msg)

    def is_sym(self, s, k=0):
        t = self.peek(k)
        return t.kind == SYM and t.text == s and self.i + k < self.limit

    def is_kw(self, kw, k=0):
        t = self.peek(k)
        return t.kind == KEYWORD and t.text == kw and self.i + k < self.limit

    def is_particle(self, p=None, k=0):
        t = self.peek(k)
        return t.kind == PARTICLE and (p is None or t.text == p) and self.i + k < self.limit

    def expect_sym(self, s):
        t = self.tok()
        if not (t.kind == SYM and t.text == s):
            self.error(t.pos, f"'{s}' 필요 — {self.describe(t)}이(가) 있습니다")
        return self.next()

    def expect_kw(self, kw):
        t = self.tok()
        if not (t.kind == KEYWORD and t.text == kw):
            self.error(t.pos, f"'{kw}' 필요 — {self.describe(t)}이(가) 있습니다")
        return self.next()

    def expect_end(self):
        t = self.tok()
        if t.kind != END:
            self.error(t.pos, f"문장 끝에 '.' 필요 — {self.describe(t)}이(가) 있습니다")
        return self.next()

    @staticmethod
    def describe(t):
        if t.kind == EOF:
            return "파일 끝"
        if t.kind == END:
            return "'.'"
        return f"'{t.text}'"

    def name_token(self, what="이름"):
        """이름 위치의 단어. 분리하지 않는다."""
        t = self.tok()
        if t.kind in (WORD, IDENT):
            if t.kind == WORD and t.text.endswith("의") and len(t.text) > 1:
                self.error(t.pos, f"'의'로 끝나는 이름은 선언할 수 없습니다: '{t.text}'")
            return self.next().text
        if t.kind == KEYWORD and t.text == "시작하기":
            return self.next().text
        self.error(t.pos, f"{what}이 필요합니다 — {self.describe(t)}이(가) 있습니다")

    # ---------- 타입 ----------
    def is_type_start(self, k=0):
        t = self.peek(k)
        if self.i + k >= self.limit:
            return False
        if t.kind == KEYWORD and (t.text in BASE_TYPES or t.text == "부호없는"):
            return True
        if t.kind in (WORD, IDENT) and t.text in self.type_names:
            return True
        if t.kind == SYM and t.text == "[":
            return self.bracket_is_type(self.i + k)
        return False

    def bracket_is_type(self, start):
        """start 의 '[' 가 함수 타입인지 (닫는 ']' 뒤에 은/는 이 오지 않으면 타입)."""
        depth = 0
        j = start
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == SYM and t.text == "[":
                depth += 1
            elif t.kind == SYM and t.text == "]":
                depth -= 1
                if depth == 0:
                    nt = self.toks[j + 1] if j + 1 < len(self.toks) else None
                    return not (nt is not None and nt.kind == PARTICLE and nt.text in ("은", "는"))
            elif t.kind in (EOF,):
                return False
            j += 1
        return False

    def parse_type(self):
        t = self.tok()
        if t.kind == KEYWORD and t.text == "부호없는":
            self.next()
            u = self.tok()
            if not (u.kind == KEYWORD and u.text in INT_TYPES):
                self.error(u.pos, "'부호없는' 뒤에는 정수 타입이 와야 합니다")
            self.next()
            base = A.BaseType(t.pos, u.text, True)
        elif t.kind == KEYWORD and t.text in BASE_TYPES:
            self.next()
            base = A.BaseType(t.pos, t.text, False)
        elif t.kind in (WORD, IDENT) and t.text in self.type_names:
            self.next()
            base = A.NamedType(t.pos, t.text)
        elif t.kind == SYM and t.text == "[":
            self.next()
            params = []
            while not self.is_sym("->"):
                params.append(self.parse_type())
                if self.is_sym(","):
                    self.next()
                elif not self.is_sym("->"):
                    self.error(self.tok().pos, "함수 타입: ',' 또는 '->' 필요")
            self.expect_sym("->")
            ret = None
            if not self.is_sym("]"):
                ret = self.parse_type()
            self.expect_sym("]")
            base = A.FuncType(t.pos, params, ret)
        else:
            self.error(t.pos, f"타입이 필요합니다 — {self.describe(t)}이(가) 있습니다")
        while True:
            if self.is_kw("참조"):
                self.next()
                base = A.PtrType(t.pos, base)
            elif self.is_sym("[") and self.peek(1).kind == INT and self.peek(2).kind == SYM and self.peek(2).text == "]":
                self.next()
                n = self.next().value
                self.next()
                base = A.ArrayType(t.pos, base, n)
            else:
                return base

    # ---------- 프로그램 ----------
    def parse_program(self):
        includes = []
        decls = []
        while self.tok().kind != EOF:
            t = self.tok()
            if t.kind == KEYWORD and t.text == "포함":
                self.next()
                s = self.tok()
                if s.kind != STRING:
                    self.error(s.pos, "포함 뒤에는 파일 이름 문자열이 필요합니다")
                self.next()
                if self.tok().kind == END:
                    self.error(self.tok().pos, "포함 뒤에는 '.'을 쓰지 않습니다")
                includes.append((t.pos, s.value))
            elif t.kind == KEYWORD and t.text == "외부":
                decls.append(self.parse_extern())
            elif t.kind == SYM and t.text == "[":
                decls.append(self.parse_function())
            elif t.kind == KEYWORD and t.text in ("묶음", "합침"):
                decls.append(self.parse_struct())
            elif t.kind == KEYWORD and t.text == "나열":
                decls.append(self.parse_enum())
            elif t.kind == KEYWORD and t.text == "별칭":
                decls.append(self.parse_alias())
            elif (t.kind == KEYWORD and t.text in ("정적", "상수")) or self.is_type_start():
                d = self.parse_var_decl()
                if d.static:
                    self.error(d.pos, "'정적'은 함수 안의 변수에만 쓸 수 있습니다")
                decls.append(d)
            elif t.kind == END:
                self.error(t.pos, "'.'만 있는 빈 문장은 허용되지 않습니다")
            else:
                self.error(t.pos, f"선언이 필요합니다 — {self.describe(t)}이(가) 있습니다")
        return A.Program(self.toks[0].pos, includes, decls)

    def header_particle(self):
        t = self.tok()
        if t.kind == PARTICLE and t.text in ("은", "는"):
            self.next()
            return
        self.error(t.pos, f"'은' 또는 '는' 필요 — {self.describe(t)}이(가) 있습니다")

    def parse_function_header(self):
        """'[' 매개변수들 이름 ']' 주제조사 [-> 타입]. (이름, 매개변수, 반환타입, 가변)"""
        start = self.expect_sym("[")
        params = []
        variadic = False
        name = None
        while True:
            t = self.tok()
            if t.kind == SYM and t.text == "]":
                break
            if t.kind == SYM and t.text == "...":
                self.next()
                variadic = True
                continue
            if self.is_type_start() and not (self.peek(1).kind == SYM and self.peek(1).text == "]" and self.tok().kind in (WORD, IDENT)):
                ptype = self.parse_type()
                pt = self.tok()
                if pt.kind not in (WORD, IDENT):
                    self.error(pt.pos, f"매개변수 이름이 필요합니다 — {self.describe(pt)}이(가) 있습니다")
                self.next()
                pname, particle = split_particle(pt.text) if pt.kind == WORD else (pt.text, None)
                if pt.kind == IDENT and self.is_particle():
                    particle = self.next().text
                role = ROLE_OF.get(particle) if particle else None
                if role in ("주제", "의", "비교", "주어"):
                    self.error(pt.pos, f"매개변수에 쓸 수 없는 조사 '{particle}'")
                params.append(A.Param(pt.pos, ptype, pname, role))
                continue
            name = self.name_token("함수 이름")
            if not (self.tok().kind == SYM and self.tok().text == "]"):
                self.error(self.tok().pos, f"함수 이름 뒤에는 ']'가 와야 합니다 — {self.describe(self.tok())}이(가) 있습니다")
            break
        if name is None:
            self.error(start.pos, "함수 이름이 없습니다")
        self.expect_sym("]")
        self.header_particle()
        ret = None
        if self.is_sym("->"):
            self.next()
            ret = self.parse_type()
        return start.pos, name, params, ret, variadic

    def parse_function(self):
        pos, name, params, ret, variadic = self.parse_function_header()
        if variadic:
            self.error(pos, "가변 인자 함수 정의는 지원하지 않습니다 (외부 선언에서만 '...' 허용)")
        body = self.parse_block()
        return A.FuncDecl(pos, name, params, ret, body)

    def parse_extern(self):
        kw = self.next()
        link = None
        if self.tok().kind == STRING:
            link = self.next().value
        pos, name, params, ret, variadic = self.parse_function_header()
        self.expect_end()
        return A.FuncDecl(kw.pos, name, params, ret, None, link_name=link or name, variadic=variadic)

    def struct_header_name(self):
        t = self.tok()
        if t.kind == WORD:
            self.next()
            if t.text.endswith("은") or t.text.endswith("는"):
                if len(t.text) < 2:
                    self.error(t.pos, "이름이 필요합니다")
                return t.text[:-1]
            if self.is_particle("은") or self.is_particle("는"):
                self.next()
                return t.text
            self.error(t.pos, "선언 이름 뒤에는 '은' 또는 '는'이 와야 합니다")
        if t.kind == IDENT:
            self.next()
            self.header_particle()
            return t.text
        self.error(t.pos, f"이름이 필요합니다 — {self.describe(t)}이(가) 있습니다")

    def parse_struct(self):
        kw = self.next()
        name = self.struct_header_name()
        fields = []
        while True:
            ftype = self.parse_type()
            fname = self.name_token("필드 이름")
            fields.append((ftype, fname))
            if self.is_sym(","):
                self.next()
                continue
            break
        self.expect_end()
        self.type_names.add(name)
        return A.StructDecl(kw.pos, name, fields, is_union=(kw.text == "합침"))

    def parse_enum(self):
        kw = self.next()
        name = self.struct_header_name()
        self.expect_sym("{")
        values = []
        while not self.is_sym("}"):
            values.append(self.name_token("나열 값 이름"))
            if self.is_sym(","):
                self.next()
            elif not self.is_sym("}"):
                self.error(self.tok().pos, "나열: ',' 또는 '}' 필요")
        self.expect_sym("}")
        self.type_names.add(name)
        return A.EnumDecl(kw.pos, name, values)

    def parse_alias(self):
        kw = self.next()
        name = self.struct_header_name()
        t = self.parse_type()
        self.expect_end()
        self.type_names.add(name)
        return A.AliasDecl(kw.pos, name, t)

    def parse_var_decl(self, need_end=True):
        pos = self.tok().pos
        static = const = False
        while self.tok().kind == KEYWORD and self.tok().text in ("정적", "상수"):
            if self.next().text == "정적":
                static = True
            else:
                const = True
        vtype = self.parse_type()
        t = self.tok()
        if t.kind == SYM and t.text == "=":
            self.error(t.pos, "변수 이름이 필요합니다 — '='이(가) 있습니다")
        if t.kind == WORD and (t.text.endswith("은") or t.text.endswith("는")) and len(t.text) > 1 \
                and not (self.peek(1).kind == SYM and self.peek(1).text == "=") and self.peek(1).kind != END:
            self.error(t.pos, "선언 초기화는 '=' 를 씁니다 ('이름은 값' 형식은 없습니다)")
        name = self.name_token("변수 이름")
        init = None
        if self.is_sym("="):
            self.next()
            init = self.parse_expr_until_end() if need_end else self.parse_expr()
        if need_end:
            self.expect_end()
        return A.VarDecl(pos, vtype, name, init, static=static, const=const)

    # ---------- 문장 ----------
    def parse_block(self):
        start = self.expect_sym("{")
        stmts = []
        while not self.is_sym("}"):
            if self.tok().kind == EOF:
                self.error(start.pos, "'}'가 닫히지 않았습니다")
            stmts.extend(self.parse_statement())
        self.expect_sym("}")
        return A.Block(start.pos, stmts)

    def parse_statement(self):
        """문장 하나(연결된 SOV 문은 여러 개)를 리스트로 반환."""
        t = self.tok()
        if t.kind == KEYWORD:
            if t.text == "반환":
                self.next()
                value = None
                if self.tok().kind != END:
                    value = self.parse_expr_until_end()
                self.expect_end()
                return [A.Return(t.pos, value)]
            if t.text == "탈출":
                self.next(); self.expect_end()
                return [A.Break(t.pos)]
            if t.text == "계속":
                self.next(); self.expect_end()
                return [A.Continue(t.pos)]
            if t.text == "갈래":
                return [self.parse_switch()]
            if t.text == "반복":
                return [self.parse_for()]
            if t.text == "반복하기":
                return [self.parse_do_while()]
            if t.text in ("정적", "상수"):
                return [self.parse_var_decl()]
            if t.text == "아니면":
                self.error(t.pos, "'아니면' 앞에 조건문이 없습니다")
            if t.text in ("포함", "외부", "묶음", "나열", "합침", "별칭"):
                self.error(t.pos, f"'{t.text}' 선언은 함수 밖에서만 할 수 있습니다")
        if t.kind == SYM and t.text == "{":
            return [self.parse_block()]
        if t.kind == WORD and t.text in ("만약정의", "만약미정의", "정의", "끝"):
            self.error(t.pos, f"'{t.text}'는 지원하지 않습니다 (조건부 컴파일과 매크로는 없습니다)")
        if self.is_type_start():
            return [self.parse_var_decl()]
        if t.kind == END:
            self.error(t.pos, "'.'만 있는 빈 문장은 허용되지 않습니다")
        if t.kind == SYM and t.text == "[" and not self.bracket_is_type(self.i):
            self.error(t.pos, "함수 정의는 함수 안에 둘 수 없습니다")
        return self.parse_clause()

    def scan_clause(self):
        """현재 위치부터 깊이 0의 '.'(END) 또는 '{' 까지. (끝 인덱스, 종류)"""
        depth = 0
        j = self.i
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == SYM and t.text in "([":
                depth += 1
            elif t.kind == SYM and t.text in ")]":
                depth -= 1
                if depth < 0:
                    self.error(t.pos, f"짝이 맞지 않는 '{t.text}'")
            elif depth == 0 and t.kind == END:
                return j, "end"
            elif depth == 0 and t.kind == SYM and t.text == "{":
                return j, "block"
            elif t.kind == EOF or (depth == 0 and t.kind == SYM and t.text == "}"):
                self.error(self.toks[self.i].pos, "문장 끝에 '.'이 없습니다")
            j += 1
        self.error(self.toks[self.i].pos, "문장 끝에 '.'이 없습니다")

    STMT_KEYWORDS = {"반환", "탈출", "계속", "갈래", "반복", "반복하기", "아니면", "정적", "상수"}

    def parse_clause(self):
        start = self.tok()
        j, kind = self.scan_clause()
        depth = 0
        for k in range(self.i + 1, j):
            t = self.toks[k]
            if t.kind == SYM and t.text in "([":
                depth += 1
            elif t.kind == SYM and t.text in ")]":
                depth -= 1
            elif depth == 0 and t.kind == KEYWORD and (t.text in self.STMT_KEYWORDS or t.text in BASE_TYPES):
                self.error(t.pos, f"문장 끝에 '.' 필요 — '{t.text}' 앞에서 문장이 끝나야 합니다")
        if kind == "block":
            return [self.parse_conditional(j)]
        # 대입?
        k = self.find_top_level_assign(self.i, j)
        if k is not None:
            target = self.parse_expr_range(self.i, k)
            op = self.toks[k].text
            self.i = k + 1
            value = self.parse_expr_range(self.i, j)
            self.i = j
            self.expect_end()
            return [A.Assign(start.pos, target, op, value)]
        last = self.toks[j - 1]
        if last.kind == WORD and strip_verb_ending(last.text)[0] is not None:
            stmts = self.parse_sov_clauses(self.i, j)
            self.i = j
            self.expect_end()
            return stmts
        if last.kind == SYM and last.text == ")":
            e = self.parse_expr_range(self.i, j)
            self.i = j
            self.expect_end()
            if not isinstance(e, A.Call):
                self.error(start.pos, "호출이 아닌 식은 문장이 될 수 없습니다")
            return [A.ExprStmt(start.pos, e)]
        if last.kind == KEYWORD and last.text == "이면":
            self.error(last.pos, "조건문 뒤에는 '{' 블록이 와야 합니다")
        self.error(start.pos, f"문장이 아닙니다 — {self.describe(start)}(으)로 시작해서 {self.describe(last)}(으)로 끝납니다")

    def find_top_level_assign(self, a, b):
        depth = 0
        for k in range(a, b):
            t = self.toks[k]
            if t.kind == SYM:
                if t.text in "([":
                    depth += 1
                elif t.text in ")]":
                    depth -= 1
                elif depth == 0 and t.text in ASSIGN_OPS:
                    return k
        return None

    # ----- 조건문 / 반복문 (블록으로 끝나는 절) -----
    def parse_conditional(self, j):
        """self.i .. j 가 조건 토큰, toks[j] 는 '{'."""
        start = self.tok()
        last = self.toks[j - 1]
        if last.kind == KEYWORD and last.text == "동안" or (last.kind == WORD and last.text.endswith("동안") and len(last.text) > 2):
            cond = self.parse_condition_tokens(self.i, j - 1, last, "동안")
            self.i = j
            body = self.parse_block()
            return A.While(start.pos, cond, body)
        cond = self.parse_condition_tokens(self.i, j - 1, last, "이면")
        self.i = j
        then = self.parse_block()
        elifs = []
        else_ = None
        while self.is_kw("아니면"):
            self.next()
            if self.is_sym("{"):
                else_ = self.parse_block()
                break
            j2, kind2 = self.scan_clause()
            if kind2 != "block":
                self.error(self.tok().pos, "'아니면' 뒤에는 '{' 또는 조건이 와야 합니다")
            c2 = self.parse_condition_tokens(self.i, j2 - 1, self.toks[j2 - 1], "이면")
            self.i = j2
            elifs.append((c2, self.parse_block()))
        return A.If(start.pos, cond, then, elifs, else_)

    def parse_condition_tokens(self, a, last_index, last, ending):
        """조건 토큰 a..last_index (last 는 이면/동안 또는 그것으로 끝나는 단어)."""
        if last.kind == KEYWORD and last.text == ending:
            b = last_index
            extra = None
        elif last.kind == WORD and last.text.endswith(ending) and len(last.text) > len(ending):
            b = last_index
            extra = last.text[: -len(ending)]
        elif ending == "이면" and last.kind == WORD and last.text.endswith("면"):
            return self.parse_compare_condition(a, last_index + 1)
        else:
            self.error(last.pos, f"조건문의 끝에 '{ending}'이 필요합니다 — {self.describe(last)}이(가) 있습니다")
        if extra is not None:
            # '맞음이면', 'b이면': 마지막 단어의 앞부분을 이름 토큰으로 바꿔 식에 포함한다
            from .lexer import Token
            kind = IDENT if not any(is_hangul(c) for c in extra) else WORD
            saved = self.toks[last_index]
            self.toks[last_index] = Token(kind, extra, last.pos)
            try:
                return self.parse_expr_range(a, last_index + 1)
            finally:
                self.toks[last_index] = saved
        if b == a:
            self.error(last.pos, "조건식이 비어 있습니다")
        return self.parse_expr_range(a, b)

    def parse_compare_condition(self, a, b):
        """X이/가 Y보다 비교동사(으)면 형식."""
        verb = self.toks[b - 1].text
        root = verb[:-1]
        if root.endswith("으"):
            root = root[:-1]
        if root not in COMPARE_VERBS:
            self.error(self.toks[b - 1].pos, f"조건문의 끝에 '이면'이 필요합니다 — '{verb}'이(가) 있습니다")
        # 주어 경계
        subj_end = None
        for k in range(a, b - 1):
            t = self.toks[k]
            if t.kind == PARTICLE and t.text in ("이", "가"):
                subj_end = k; subj_tokens = (a, k); break
            if t.kind == WORD and len(t.text) > 1 and t.text[-1] in "이가":
                subj_end = k; subj_tokens = None; break
        if subj_end is None:
            self.error(self.toks[a].pos, "비교 조건: '이/가' 주어가 필요합니다 (예: 값이 0보다 크면)")
        boda = None
        for k in range(subj_end + 1, b - 1):
            t = self.toks[k]
            if t.kind == PARTICLE and t.text == "보다":
                boda = k
        if boda is None:
            self.error(self.toks[a].pos, "비교 조건: '보다'가 필요합니다")
        if subj_tokens is None:
            w = self.toks[subj_end]
            left = A.Name(w.pos, w.text[:-1])
            if subj_end != a:
                self.error(w.pos, "비교 조건의 주어는 하나의 이름이어야 합니다")
        else:
            left = self.parse_expr_range(a, subj_end)
        right = self.parse_expr_range(subj_end + 1, boda)
        return A.Binary(self.toks[a].pos, COMPARE_VERBS[root], left, right)

    def parse_switch(self):
        kw = self.next()
        self.expect_sym("(")
        subject = self.parse_expr_until_sym(")")
        self.expect_sym(")")
        self.expect_sym("{")
        cases = []
        default = None
        while not self.is_sym("}"):
            if self.is_kw("경우"):
                self.next()
                value = self.parse_expr_until_sym(":")
                self.expect_sym(":")
                cases.append((value, self.parse_block()))
            elif self.is_kw("기본"):
                self.next()
                self.expect_sym(":")
                if default is not None:
                    self.error(kw.pos, "'기본'은 하나만 둘 수 있습니다")
                default = self.parse_block()
            else:
                self.error(self.tok().pos, f"'경우' 또는 '기본' 필요 — {self.describe(self.tok())}이(가) 있습니다")
        self.expect_sym("}")
        return A.Switch(kw.pos, subject, cases, default)

    def parse_for(self):
        kw = self.next()
        self.expect_sym("(")
        init = None
        if not self.is_sym(":"):
            if self.is_type_start() or self.is_kw("상수"):
                init = self.parse_var_decl(need_end=False)
            else:
                k = self.find_until_sym(":")
                init = self.parse_assign_body(self.i, k)
        self.expect_sym(":")
        cond = self.parse_expr_until_sym(":")
        self.expect_sym(":")
        step = None
        if not self.is_sym(")"):
            k = self.find_until_sym(")")
            last = self.toks[k - 1]
            if last.kind == WORD and strip_verb_ending(last.text)[0] is not None:
                stmts = self.parse_sov_clauses(self.i, k)
                if len(stmts) != 1:
                    self.error(last.pos, "반복문 증감 단계에는 문장 하나만 올 수 있습니다")
                step = stmts[0]
                self.i = k
            else:
                step = self.parse_assign_body(self.i, k)
        self.expect_sym(")")
        body = self.parse_block()
        return A.For(kw.pos, init, cond, step, body)

    def parse_assign_body(self, a, b):
        k = self.find_top_level_assign(a, b)
        if k is None:
            self.error(self.toks[a].pos, "대입이 필요합니다")
        target = self.parse_expr_range(a, k)
        value = self.parse_expr_range(k + 1, b)
        self.i = b
        return A.Assign(self.toks[a].pos, target, self.toks[k].text, value)

    def parse_do_while(self):
        kw = self.next()
        body = self.parse_block()
        self.expect_sym("(")
        cond = self.parse_expr_until_sym(")")
        self.expect_sym(")")
        t = self.tok()
        if t.kind == KEYWORD and t.text == "동안":
            self.next()
        else:
            self.error(t.pos, f"'동안' 필요 — {self.describe(t)}이(가) 있습니다")
        self.expect_end()
        return A.DoWhile(kw.pos, body, cond)

    def find_until_sym(self, s):
        depth = 0
        j = self.i
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == SYM and t.text in "([":
                depth += 1
            elif t.kind == SYM and t.text in ")]":
                if depth == 0 and t.text == s:
                    return j
                depth -= 1
            elif depth == 0 and t.kind == SYM and t.text == s:
                return j
            elif t.kind in (EOF, END):
                break
            j += 1
        self.error(self.toks[self.i].pos, f"'{s}' 필요")

    # ----- SOV 문 -----
    def parse_sov_clauses(self, a, b):
        """토큰 a..b 를 연결된 SOV 절들로. 각 절은 문장으로 변환."""
        stmts = []
        clause_start = a
        depth = 0
        for k in range(a, b):
            t = self.toks[k]
            if t.kind == SYM and t.text in "([":
                depth += 1
            elif t.kind == SYM and t.text in ")]":
                depth -= 1
            elif depth == 0 and t.kind == WORD and k == b - 1 or (depth == 0 and t.kind == WORD and self.is_chain_verb(t.text)):
                root, ending = strip_verb_ending(t.text)
                if root is None:
                    continue
                if k != b - 1 and ending == "다":
                    self.error(t.pos, f"'{t.text}' 뒤에 문장이 이어집니다 — 이어 쓰려면 '-고' 또는 '-서'를 씁니다")
                if k == b - 1 and ending != "다":
                    self.error(t.pos, f"문장은 '-다'로 끝나야 합니다 — '{t.text}'이(가) 있습니다")
                stmts.append(self.make_sov_stmt(clause_start, k, root, t))
                clause_start = k + 1
        if not stmts:
            self.error(self.toks[a].pos, "동사가 없습니다")
        return stmts

    @staticmethod
    def is_chain_verb(text):
        return len(text) >= 2 and text[-1] in "고서" and not text.endswith("보고")

    def make_sov_stmt(self, a, v, root, verb_tok):
        args = self.parse_sov_args(a, v)
        base = verb_base(root)
        if base in ("증가", "감소"):
            if len(args) != 1 or args[0][1] != "대상":
                self.error(verb_tok.pos, f"'{verb_tok.text}'에는 '을/를' 대상 하나가 필요합니다")
            return A.IncDec(verb_tok.pos, args[0][0], 1 if base == "증가" else -1)
        if base == "반환":
            if len(args) != 1 or args[0][1] != "대상":
                self.error(verb_tok.pos, "'반환하다'에는 '을/를' 대상 하나가 필요합니다")
            return A.Return(verb_tok.pos, args[0][0])
        return A.ExprStmt(self.toks[a].pos if a < v else verb_tok.pos, A.SOVCall(verb_tok.pos, args, root))

    def parse_sov_args(self, a, v):
        """토큰 a..v 를 (식, 역할) 목록으로. 인자 위치의 단어는 끝 접사를 뗀다."""
        groups = []
        cur = []          # 현재 그룹 토큰 (원 토큰 또는 대체 토큰)
        depth = 0
        k = a
        while k < v:
            t = self.toks[k]
            if t.kind == SYM and t.text in "([":
                depth += 1; cur.append(t)
            elif t.kind == SYM and t.text in ")]":
                depth -= 1; cur.append(t)
            elif depth == 0 and t.kind == PARTICLE:
                if t.text == "의":
                    cur.append(t)
                else:
                    if not cur:
                        self.error(t.pos, f"조사 '{t.text}' 앞에 인자가 없습니다")
                    groups.append((cur, t.text, t.pos)); cur = []
            elif depth == 0 and t.kind == WORD:
                name, particle = split_particle(t.text)
                if particle is None:
                    cur.append(t)
                elif particle == "의":
                    cur.append(t)   # 식 파서가 '의' 를 처리
                else:
                    from .lexer import Token
                    cur.append(Token(WORD, name, t.pos))
                    groups.append((cur, particle, t.pos)); cur = []
            else:
                cur.append(t)
            k += 1
        if cur:
            groups.append((cur, None, cur[0].pos))
        args = []
        for toks, particle, pos in groups:
            expr = self.parse_expr_tokens(toks)
            role = ROLE_OF.get(particle) if particle else None
            if role in ("주제", "주어", "의", "비교"):
                self.error(pos, f"인자에 쓸 수 없는 조사 '{particle}'")
            args.append((expr, role))
        return args

    # ---------- 식 ----------
    def parse_expr_tokens(self, toks):
        """임시 토큰 목록으로 식 파싱 (SOV 인자)."""
        from .lexer import Token
        saved = (self.toks, self.i, self.limit)
        self.toks = list(toks) + [Token(EOF, "", toks[-1].pos if toks else saved[0][saved[1]].pos)]
        self.i = 0
        self.limit = len(toks)
        try:
            if not toks:
                self.error(self.toks[0].pos, "식이 비어 있습니다")
            e = self.parse_expr()
            if self.i != self.limit:
                t = self.tok()
                self.error(t.pos, f"식 뒤에 {self.describe(t)}이(가) 남았습니다")
            return e
        finally:
            self.toks, self.i, self.limit = saved

    def parse_expr_range(self, a, b):
        saved_i, saved_limit = self.i, self.limit
        self.i, self.limit = a, b
        try:
            if a >= b:
                self.error(self.toks[a].pos, "식이 필요합니다")
            e = self.parse_expr()
            if self.i != b:
                t = self.tok()
                self.error(t.pos, f"식 뒤에 {self.describe(t)}이(가) 남았습니다")
            return e
        finally:
            self.i, self.limit = b, saved_limit

    def parse_expr_until_end(self):
        j, kind = self.scan_clause()
        if kind != "end":
            self.error(self.toks[j].pos, "식 뒤에 '.'이 필요합니다")
        return self.parse_expr_range(self.i, j)

    def parse_expr_until_sym(self, s):
        k = self.find_until_sym(s)
        return self.parse_expr_range(self.i, k)

    def parse_expr(self):
        return self.parse_ternary()

    def parse_ternary(self):
        cond = self.parse_binary(0)
        if self.is_sym("?"):
            self.next()
            a = self.parse_ternary()
            self.expect_sym(":")
            b = self.parse_ternary()
            return A.Ternary(cond.pos, cond, a, b)
        return cond

    def parse_binary(self, level):
        if level >= len(BINARY_PREC):
            return self.parse_unary()
        ops = BINARY_PREC[level]
        left = self.parse_binary(level + 1)
        while not self.at_limit():
            t = self.tok()
            if (t.kind == SYM or t.kind == KEYWORD) and t.text in ops:
                self.next()
                right = self.parse_binary(level + 1)
                left = A.Binary(t.pos, t.text, left, right)
            else:
                break
        return left

    def parse_unary(self):
        t = self.tok()
        if not self.at_limit():
            if t.kind == SYM and t.text in ("-", "~", "&"):
                self.next()
                operand = self.parse_unary()
                if t.text == "-" and isinstance(operand, A.IntLit):
                    return A.IntLit(t.pos, -operand.value)      # 음수 리터럴은 리터럴이다 (범위 검사를 위해)
                if t.text == "-" and isinstance(operand, A.FloatLit):
                    return A.FloatLit(t.pos, -operand.value)
                return A.Unary(t.pos, t.text, operand)
            if t.kind == KEYWORD and t.text == "아닌":
                self.next()
                return A.Unary(t.pos, "아닌", self.parse_unary())
            if t.kind == KEYWORD and t.text == "크기":
                self.next()
                self.expect_sym("(")
                ty = self.parse_type()
                self.expect_sym(")")
                return A.SizeOf(t.pos, ty)
            if t.kind == SYM and t.text == "*":
                self.error(t.pos, "단항 '*'는 없습니다 — 역참조는 p[0] 을 씁니다")
        return self.parse_cast()

    def parse_cast(self):
        e = self.parse_postfix()
        # 식으로 타입 / 식로 타입
        if not self.at_limit() and self.tok().kind == PARTICLE and self.tok().text in ("로", "으로") and self.is_type_start(1):
            self.next()
            ty = self.parse_type()
            return A.Cast(e.pos, e, ty)
        return e

    def parse_postfix(self):
        e = self.parse_primary()
        while not self.at_limit():
            t = self.tok()
            if t.kind == SYM and t.text == "[":
                self.next()
                idx = self.parse_expr_until_sym("]")
                self.expect_sym("]")
                e = A.Index(t.pos, e, idx)
            elif t.kind == PARTICLE and t.text == "의":
                self.next()
                e = self.member_chain(e)
            elif t.kind == SYM and t.text == "->":
                self.next()
                e = A.Member(t.pos, e, self.member_name(), True)
            elif t.kind == SYM and t.text == "(":
                self.next()
                args = []
                while not self.is_sym(")"):
                    args.append(self.parse_expr_until_arg_end())
                    if self.is_sym(","):
                        self.next()
                    elif not self.is_sym(")"):
                        self.error(self.tok().pos, "호출 인자: ',' 또는 ')' 필요")
                self.expect_sym(")")
                e = A.Call(t.pos, e, args)
            else:
                break
        return e

    def parse_expr_until_arg_end(self):
        """호출 인자: 깊이 0 의 ',' 또는 ')' 까지."""
        depth = 0
        j = self.i
        while j < self.limit:
            t = self.toks[j]
            if t.kind == SYM and t.text in "([":
                depth += 1
            elif t.kind == SYM and t.text in ")]":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and t.kind == SYM and t.text == ",":
                break
            j += 1
        return self.parse_expr_range(self.i, j)

    def member_chain(self, base):
        """base 뒤에 멤버 이름이 온다. 멤버 이름이 '의'로 끝나면 연쇄 (a의 b의 c)."""
        while True:
            t = self.tok()
            if self.at_limit() or t.kind not in (WORD, IDENT):
                self.error(t.pos, f"멤버 이름이 필요합니다 — {self.describe(t)}이(가) 있습니다")
            self.next()
            if t.kind == WORD and t.text.endswith("의") and len(t.text) > 1:
                base = A.Member(t.pos, base, t.text[:-1], False)
                continue
            return A.Member(t.pos, base, t.text, False)

    def member_name(self):
        t = self.tok()
        if not self.at_limit() and t.kind in (WORD, IDENT):
            self.next()
            if t.kind == WORD and t.text.endswith("의") and len(t.text) > 1:
                self.error(t.pos, "'->' 뒤의 멤버 이름에는 '의'를 붙여 쓸 수 없습니다 — 공백으로 띄웁니다")
            return t.text
        self.error(t.pos, f"멤버 이름이 필요합니다 — {self.describe(t)}이(가) 있습니다")

    def parse_primary(self):
        t = self.tok()
        if self.at_limit():
            self.error(t.pos, "식이 필요합니다")
        if t.kind == INT:
            self.next(); return A.IntLit(t.pos, t.value)
        if t.kind == FLOAT:
            self.next(); return A.FloatLit(t.pos, t.value)
        if t.kind == CHAR:
            self.next(); return A.CharLit(t.pos, t.value)
        if t.kind == STRING:
            self.next(); return A.StringLit(t.pos, t.value, t.text)
        if t.kind == KEYWORD:
            if t.text == "참":
                self.next(); return A.BoolLit(t.pos, True)
            if t.text == "거짓":
                self.next(); return A.BoolLit(t.pos, False)
            if t.text == "없음":
                self.next(); return A.NullLit(t.pos)
            if t.text in BASE_TYPES or t.text == "부호없는":
                self.error(t.pos, f"식이 필요합니다 — 타입 '{t.text}'이(가) 있습니다")
            self.error(t.pos, f"식이 필요합니다 — 키워드 '{t.text}'이(가) 있습니다")
        if t.kind in (WORD, IDENT):
            self.next()
            text = t.text
            if t.kind == WORD and text.endswith("의") and len(text) > 1:
                # 식 위치의 '의' 분리: 이름 + 멤버 접근 (연쇄 가능)
                return self.member_chain(A.Name(t.pos, text[:-1]))
            if t.kind == WORD and self.is_type_start(0):
                for suffix in ("으로", "로"):
                    if text.endswith(suffix) and len(text) > len(suffix):
                        # 식로 타입 (붙여 쓴 형변환)
                        ty = self.parse_type()
                        return A.Cast(t.pos, A.Name(t.pos, text[: -len(suffix)]), ty)
            return A.Name(t.pos, text)
        if t.kind == SYM and t.text == "(":
            close = self.find_matching_paren(self.i)
            inner_last = self.toks[close - 1]
            self.next()
            if inner_last.kind == WORD and strip_verb_ending(inner_last.text)[0] is not None and inner_last.text[-1] == "다" \
                    and not (inner_last.kind == KEYWORD):
                # SOV 식
                stmts = self.parse_sov_clauses(self.i, close)
                if len(stmts) != 1 or not isinstance(stmts[0], A.ExprStmt):
                    self.error(t.pos, "괄호 안의 SOV 문은 값을 내는 호출 하나여야 합니다")
                self.i = close
                self.expect_sym(")")
                return stmts[0].expr
            e = self.parse_expr_range(self.i, close)
            self.i = close
            self.expect_sym(")")
            return e
        if t.kind == PARTICLE:
            self.error(t.pos, f"식이 필요합니다 — 조사 '{t.text}'이(가) 있습니다")
        self.error(t.pos, f"식이 필요합니다 — {self.describe(t)}이(가) 있습니다")

    def find_matching_paren(self, start):
        depth = 0
        j = start
        while j < self.limit:
            t = self.toks[j]
            if t.kind == SYM and t.text in "([":
                depth += 1
            elif t.kind == SYM and t.text in ")]":
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        self.error(self.toks[start].pos, "괄호가 닫히지 않았습니다")


def parse(tokens, filename):
    return Parser(tokens, filename).parse_program()
