"""G0 semantic model and interpreter. No C parser or code generator dependency."""
from dataclasses import dataclass
import re
import unicodedata

MIN = -(2 ** 31)
END = 2 ** 31
PROFILE = 'geul-g0/int32-decisions/v1'
MAX_BYTES = 1024 * 1024
MAX_RULES = 1024


class ReviewError(ValueError):
    def __init__(self, code, message, line=None):
        self.code, self.message, self.line = code, message, line
        super().__init__(f'{code}' + (f':{line}' if line else '') + f': {message}')


def name_ok(name):
    return (isinstance(name, str) and 0 < len(name) <= 128
            and unicodedata.normalize('NFC', name) == name
            and re.fullmatch(r'[^\W\d]\w*', name, flags=re.UNICODE) is not None)


def int32(value):
    if type(value) is not int or not MIN <= value < END:
        raise ReviewError('INT32', '부호 있는 32비트 정수가 필요합니다.')
    return value


@dataclass(frozen=True)
class Rule:
    lower: int
    upper: int
    value: int

    def __post_init__(self):
        if (type(self.lower) is not int or type(self.upper) is not int
                or not MIN <= self.lower < self.upper <= END):
            raise ReviewError('RANGE', '구간의 경계 또는 순서가 잘못됐습니다.')
        int32(self.value)


@dataclass(frozen=True)
class Program:
    name: str
    input_name: str
    rules: tuple[Rule, ...]

    def __post_init__(self):
        if not name_ok(self.name) or not name_ok(self.input_name):
            raise ReviewError('NAME', 'NFC 이름은 글자 또는 밑줄로 시작해야 합니다.')
        if not isinstance(self.rules, tuple) or not 1 <= len(self.rules) <= MAX_RULES:
            raise ReviewError('LIMIT', f'규칙은 1~{MAX_RULES}개의 불변 목록이어야 합니다.')
        next_lower = MIN
        for rule in self.rules:
            if not isinstance(rule, Rule):
                raise ReviewError('TYPE', '규칙 타입이 잘못됐습니다.')
            if rule.lower != next_lower:
                raise ReviewError('COVERAGE', '입력 구간의 누락, 겹침 또는 순서 오류입니다.')
            next_lower = rule.upper
        if next_lower != END:
            raise ReviewError('COVERAGE', 'int32 전체 입력 구간을 덮어야 합니다.')


def integer(text, line=None):
    # Bound length before int() to avoid pathological numeric input.
    if len(text) > 11 or re.fullmatch(r'(?:0|-?[1-9][0-9]*)', text) is None:
        raise ReviewError('INTEGER', '정규 십진 정수 표기가 필요합니다.', line)
    return int(text)


def parse(source):
    if len(source.encode('utf-8')) > MAX_BYTES:
        raise ReviewError('LIMIT', '소스 크기 한계 1MiB를 넘었습니다.')
    if unicodedata.normalize('NFC', source) != source:
        raise ReviewError('NFC', '소스는 NFC 형식이어야 합니다.')
    lines = [(n, s.strip()) for n, s in enumerate(source.splitlines(), 1) if s.strip()]
    if not lines:
        raise ReviewError('SYNTAX', '프로그램 헤더가 없습니다.', 1)
    if len(lines) > MAX_RULES + 1:
        raise ReviewError('LIMIT', '규칙 개수 한계를 넘었습니다.')
    n, header = lines[0]
    h = re.fullmatch(r'「([^」]+)」는 부호 있는 32비트 정수 「([^」]+)」으로 결정한다\.', header)
    if h is None:
        raise ReviewError('SYNTAX', 'G0 헤더 형식이 아닙니다.', n)
    title, arg = h.groups()
    rules = []
    for n, line in lines[1:]:
        m = re.fullmatch(r'「([^」]+)」이 (.+)이면 ([^ ]+)을 돌려준다\.', line)
        if m is None:
            raise ReviewError('SYNTAX', 'G0 조건·반환 문장 형식이 아닙니다.', n)
        subject, condition, output = m.groups()
        if subject != arg:
            raise ReviewError('NAME', '헤더에서 선언한 입력 이름과 다릅니다.', n)
        both = re.fullmatch(r'([^ ]+) 이상 ([^ ]+) 미만', condition)
        less = re.fullmatch(r'([^ ]+) 미만', condition)
        more = re.fullmatch(r'([^ ]+) 이상', condition)
        if both:
            lo, hi = (integer(v, n) for v in both.groups())
            if lo == MIN or hi == END:
                raise ReviewError('SYNTAX', '끝 구간은 미만/이상 표기로 적습니다.', n)
        elif less:
            lo, hi = MIN, integer(less[1], n)
            if hi == END:
                raise ReviewError('SYNTAX', '전체 구간은 모든 범위로 적습니다.', n)
        elif more:
            lo, hi = integer(more[1], n), END
            if lo == MIN:
                raise ReviewError('SYNTAX', '전체 구간은 모든 범위로 적습니다.', n)
        elif condition == '모든 범위':
            lo, hi = MIN, END
        else:
            raise ReviewError('SYNTAX', '지원하지 않는 조건입니다.', n)
        try:
            rules.append(Rule(lo, hi, integer(output, n)))
        except ReviewError as e:
            raise ReviewError(e.code, e.message, n) from e
    return Program(title, arg, tuple(rules))


def normalize(program):
    out = []
    for rule in program.rules:
        if out and out[-1].value == rule.value:
            out[-1] = Rule(out[-1].lower, rule.upper, rule.value)
        else:
            out.append(rule)
    return Program(program.name, program.input_name, tuple(out))


def render(program):
    program = normalize(program)
    out = [f'「{program.name}」는 부호 있는 32비트 정수 「{program.input_name}」으로 결정한다.']
    for rule in program.rules:
        if rule.lower == MIN and rule.upper == END:
            condition = '모든 범위'
        elif rule.lower == MIN:
            condition = f'{rule.upper} 미만'
        elif rule.upper == END:
            condition = f'{rule.lower} 이상'
        else:
            condition = f'{rule.lower} 이상 {rule.upper} 미만'
        out.append(f'「{program.input_name}」이 {condition}이면 {rule.value}을 돌려준다.')
    return '\n'.join(out) + '\n'


def evaluate(program, value):
    """Independent direct interpretation of the declared rules."""
    value = int32(value)
    for rule in program.rules:
        if rule.lower <= value < rule.upper:
            return rule.value
    raise ReviewError('INTERNAL', '검사된 프로그램의 입력 구간이 누락됐습니다.')


def differences(before, after):
    """Linear interval intersection; reports the exact changed int32 inputs."""
    i = j = 0
    changes = []
    while i < len(before.rules) and j < len(after.rules):
        a, b = before.rules[i], after.rules[j]
        lo, hi = max(a.lower, b.lower), min(a.upper, b.upper)
        if lo < hi and a.value != b.value:
            if (changes and changes[-1]['maximum'] + 1 == lo
                    and changes[-1]['before'] == a.value and changes[-1]['after'] == b.value):
                changes[-1]['maximum'] = hi - 1
            else:
                changes.append({'minimum': lo, 'maximum': hi - 1,
                                'before': a.value, 'after': b.value})
        if a.upper <= b.upper:
            i += 1
        if b.upper <= a.upper:
            j += 1
    return changes
