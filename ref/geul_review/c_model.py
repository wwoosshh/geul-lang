"""Rejecting C frontend and path interval executor, independent of G0 lowering.

This module does not call the G0 interpreter, normalizer or code generator.
The analysis is complete only for its explicit comparison/constant-return subset.
"""
from dataclasses import dataclass
import re

from .core import MIN, END, MAX_BYTES, ReviewError

MAX_DEPTH = 64
MAX_NODES = 8192
MAX_PATHS = 4096
MAX_STEPS = 100000


@dataclass(frozen=True)
class Return:
    value: int


@dataclass(frozen=True)
class If:
    op: str
    value: int
    yes: tuple
    no: tuple


@dataclass(frozen=True)
class CFunction:
    name: str
    parameter: str
    body: tuple


def unsupported(message, coord=None, code='C_UNSUPPORTED'):
    raise ReviewError(code, message, getattr(coord, 'line', None))


def without_comments(source):
    if len(source.encode('utf-8')) > MAX_BYTES:
        unsupported('C 소스 크기 한계를 넘었습니다.', code='LIMIT')
    # Translation-phase splicing and trigraphs can change comment boundaries.
    if '\\' in source or '??' in source:
        unsupported('줄 연결·이스케이프·트라이그래프는 G0 범위 밖입니다.')
    # C translation normalizes physical line endings before removing comments.
    # Dropping text through LF only would swallow real code after a bare CR.
    source = source.replace('\r\n', '\n').replace('\r', '\n')
    out, i = [], 0
    while i < len(source):
        if source.startswith('//', i):
            end = source.find('\n', i + 2)
            end = len(source) if end < 0 else end
            out.append(' ' * (end - i)); i = end
        elif source.startswith('/*', i):
            end = source.find('*/', i + 2)
            if end < 0:
                unsupported('끝나지 않은 C 주석입니다.', code='C_SYNTAX')
            text = source[i:end + 2]
            out.append(''.join('\n' if c == '\n' else ' ' for c in text))
            i = end + 2
        else:
            if source[i] in '#\"\'':
                unsupported('전처리 지시문과 문자열·문자 리터럴은 지원하지 않습니다.')
            out.append(source[i]); i += 1
    return ''.join(out)


def parse_c_ast(source, filename=''):
    try:
        from pycparser import c_ast as A, c_parser
        from pycparser.plyparser import ParseError
    except ImportError as e:
        raise ReviewError('DEPENDENCY', 'requirements-review.txt의 pycparser를 설치하세요.') from e
    cleaned = without_comments(source)
    try:
        ast = c_parser.CParser().parse(cleaned, filename=filename)
    except (ParseError, RecursionError) as e:
        raise ReviewError('C_SYNTAX', str(e)) from e
    stack = [(ast, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            unsupported('C 구문 트리 한계를 넘었습니다.', code='LIMIT')
        stack.extend((child, depth + 1) for _, child in node.children())

    return ast


def function_signature(decl, definition=False):
    """Validate a prototype/definition, returning its optional int parameter name.

    None means (void); a string means one int argument. An unnamed int in a
    prototype is represented by ''. No old-style unspecified argument lists.
    """
    from pycparser import c_ast as A

    def plain_type(t, name):
        return (isinstance(t, A.TypeDecl) and not t.quals and not t.align
                and isinstance(t.type, A.IdentifierType) and t.type.names == [name])

    def plain_decl(d, storage=()):
        return (isinstance(d, A.Decl) and not d.quals and tuple(d.storage) in storage
                and not d.funcspec and not d.align and d.init is None and d.bitsize is None)

    if (not plain_decl(decl, ((),) if definition else ((), ('extern',)))
            or not isinstance(decl.type, A.FuncDecl) or not plain_type(decl.type.type, 'int')
            or decl.type.args is None or len(decl.type.args.params) != 1):
        unsupported('int 또는 void 매개변수 목록과 int 반환의 일반 함수가 필요합니다.',
                    getattr(decl, 'coord', None), code='C_SIGNATURE')
    parameter = decl.type.args.params[0]
    if isinstance(parameter, A.Typename) and not parameter.quals and not parameter.align:
        if plain_type(parameter.type, 'void'):
            result = None
        elif plain_type(parameter.type, 'int') and not definition:
            result = ''
        else:
            unsupported('지원하지 않는 매개변수 타입입니다.', parameter.coord, code='C_SIGNATURE')
    elif plain_decl(parameter, ((),)) and plain_type(parameter.type, 'int'):
        result = parameter.name
        if not result:
            unsupported('정의의 int 입력 이름이 필요합니다.', parameter.coord, code='C_SIGNATURE')
    else:
        unsupported('매개변수는 int 하나 또는 void여야 합니다.', parameter.coord, code='C_SIGNATURE')
    for name in (decl.name, result):
        if name is not None and name != '' and re.fullmatch(r'[A-Za-z][A-Za-z_0-9]*', name) is None:
            unsupported('C 이름은 ASCII 글자로 시작해야 하며 예약 식별자를 쓰지 않습니다.', code='C_SIGNATURE')
    if not decl.name:
        unsupported('함수 이름이 없습니다.', code='C_SIGNATURE')
    return result


def c_literal(node):
    from pycparser import c_ast as A

    def decimal(expr):
        if (isinstance(expr, A.Constant) and expr.type == 'int'
                and len(expr.value) <= 10 and re.fullmatch(r'0|[1-9][0-9]*', expr.value)):
            return int(expr.value)
        return None

    value = decimal(node)
    if isinstance(node, A.UnaryOp) and node.op == '-':
        child = decimal(node.expr)
        if child is not None:
            value = -child
    if (isinstance(node, A.BinaryOp) and node.op == '-'
            and isinstance(node.left, A.UnaryOp) and node.left.op == '-'
            and decimal(node.left.expr) == 2147483647 and decimal(node.right) == 1):
        value = MIN
    if value is None or not MIN <= value < END:
        unsupported('int32 정수 상수만 허용합니다.', getattr(node, 'coord', None))
    return value


def parse_c(source):
    from pycparser import c_ast as A
    ast = parse_c_ast(source)
    if len(ast.ext) != 1 or not isinstance(ast.ext[0], A.FuncDef):
        unsupported('함수 정의 하나만 허용합니다.', code='C_SIGNATURE')
    return decision_function(ast.ext[0])


def decision_function(fn, resolve_constant=None):
    """Lower a checked one-input AST to decisions, optionally resolving pure calls."""
    from pycparser import c_ast as A
    decl = fn.decl
    parameter = function_signature(decl, definition=True)
    if fn.param_decls or not parameter:
        unsupported('선택한 진입점은 이름 있는 int 입력 하나가 필요합니다.', code='C_SIGNATURE')

    def literal(node):
        if isinstance(node, A.FuncCall) and resolve_constant is not None:
            return resolve_constant(node)
        return c_literal(node)

    reverse = {'<': '>', '<=': '>=', '>': '<', '>=': '<=', '==': '==', '!=': '!='}

    def statements(node):
        if node is None:
            return ()
        if isinstance(node, A.Compound):
            result = []
            for statement in node.block_items or []:
                result.extend(statements(statement))
            return tuple(result)
        if isinstance(node, A.Return):
            return (Return(literal(node.expr)),)
        if isinstance(node, A.If):
            condition = node.cond
            if not isinstance(condition, A.BinaryOp) or condition.op not in reverse:
                unsupported('입력과 상수의 비교 조건이 필요합니다.', condition.coord)
            if isinstance(condition.left, A.ID) and condition.left.name == parameter:
                op, value = condition.op, literal(condition.right)
            elif isinstance(condition.right, A.ID) and condition.right.name == parameter:
                op, value = reverse[condition.op], literal(condition.left)
            else:
                unsupported('선언한 입력과 상수의 비교만 지원합니다.', condition.coord)
            return (If(op, value, statements(node.iftrue), statements(node.iffalse)),)
        unsupported(f'지원하지 않는 C 구문: {type(node).__name__}', node.coord)

    return CFunction(decl.name, parameter, statements(fn.body))


def true_ranges(op, value):
    """Exact integer truth sets, independent of emitter's branch structure."""
    intervals = {
        '<': [(MIN, value)], '<=': [(MIN, value + 1)],
        '>': [(value + 1, END)], '>=': [(value, END)],
        '==': [(value, value + 1)], '!=': [(MIN, value), (value + 1, END)],
    }[op]
    return [(lo, hi) for lo, hi in intervals if lo < hi]


def partition(interval, truths):
    """Split an interval by a disjoint, ordered truth set, including its complement."""
    lo, hi = interval
    yes, no, cursor = [], [], lo
    for a, b in truths:
        a, b = max(lo, a), min(hi, b)
        if a >= b:
            continue
        if cursor < a:
            no.append((cursor, a))
        yes.append((a, b))
        cursor = b
    if cursor < hi:
        no.append((cursor, hi))
    return yes, no


def execute_intervals(function):
    """Execute all int32 inputs symbolically, carrying actual fallthrough paths."""
    results = []
    steps = 0

    def execute(body, incoming):
        nonlocal steps
        live = incoming
        for statement in body:
            following = []
            for interval in live:
                steps += 1
                if steps > MAX_STEPS or len(results) + len(following) > MAX_PATHS:
                    unsupported('C 경로 분석 한계를 넘었습니다.', code='LIMIT')
                if isinstance(statement, Return):
                    results.append((*interval, statement.value))
                else:
                    yes, no = partition(interval, true_ranges(statement.op, statement.value))
                    following.extend(execute(statement.yes, yes))
                    following.extend(execute(statement.no, no))
            live = following
        return live

    pending = execute(function.body, [(MIN, END)])
    if len(results) > MAX_PATHS:
        unsupported('C 경로 개수 한계를 넘었습니다.', code='LIMIT')
    if pending:
        unsupported(f'반환 없는 입력이 있습니다: {min(lo for lo, _ in pending)}', code='C_RETURN_GAP')
    results.sort()
    cursor = MIN
    merged = []
    for lo, hi, value in results:
        if lo != cursor or hi <= lo:
            unsupported('내부 경로 분할이 완전하지 않습니다.', code='INTERNAL')
        if merged and merged[-1][2] == value:
            merged[-1] = (merged[-1][0], hi, value)
        else:
            merged.append((lo, hi, value))
        cursor = hi
    if cursor != END:
        unsupported('내부 정의역 검사 실패입니다.', code='INTERNAL')
    return tuple(merged)
