"""G0 -> C11. Emission and verification intentionally use different algorithms."""
from .core import MIN, Program, ReviewError, normalize, render


def emit_c(program: Program):
    program = normalize(program)

    def number(n):
        return '(-2147483647 - 1)' if n == MIN else str(n)

    lines = ['/* G0: requires C int range [-2147483648, 2147483647]. */',
             'int geul_review(int geul_input) {']
    for rule in program.rules[:-1]:
        lines.append(f'    if (geul_input < {rule.upper}) return {number(rule.value)};')
    lines.append(f'    return {number(program.rules[-1].value)};')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def checked_emit_c(program):
    from .verification import verify
    source = emit_c(program)
    evidence = verify(render(program), source)
    if evidence['status'] != 'equivalent_in_g0_model':
        raise ReviewError('CODEGEN', '생성한 C가 글의 의미와 다릅니다.')
    return source
