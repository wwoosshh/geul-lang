"""Full-domain model comparison and replayable evidence, not a trusted certificate authority."""
import hashlib
from pathlib import Path
import platform

from .core import PROFILE, Program, Rule, ReviewError, parse
from .c_model import parse_c, execute_intervals


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def implementation_digest():
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        h.update(path.name.encode('utf-8') + b'\0' + path.read_bytes() + b'\0')
    return h.hexdigest()


def lift(source, name=None, input_name=None):
    fn = parse_c(source)
    ranges = execute_intervals(fn)
    return Program(name or fn.name, input_name or fn.parameter,
                   tuple(Rule(lo, hi, value) for lo, hi, value in ranges))


def compare_model(program, fn):
    """Compare independent C path results with declared G0 intervals.

    No call to G0 evaluate/differences or the C code generator is used here.
    Every intersecting interval is checked, not a set of runtime sample inputs.
    """
    import pycparser
    actual = execute_intervals(fn)
    counterexample = None
    cells = 0
    # Both partitions cover the entire domain; intersect independently.
    # Linear sweep avoids a rules * paths denial of service.
    i = j = 0
    while i < len(program.rules) and j < len(actual):
        expected = program.rules[i]
        lo, hi, result = actual[j]
        a, b = max(expected.lower, lo), min(expected.upper, hi)
        if a < b:
            cells += 1
            if result != expected.value and counterexample is None:
                counterexample = {'input': a, 'glr': expected.value, 'c': result}
        if expected.upper <= hi:
            i += 1
        if hi <= expected.upper:
            j += 1
    return {
        'profile': PROFILE,
        'status': 'different' if counterexample else 'equivalent_in_g0_model',
        'method': 'complete_interval_partition',
        'domain': {'minimum': -2147483648, 'maximum': 2147483647},
        'observations': ['return_value'],
        'assumptions': ['C int is exactly signed 32-bit', 'the supplied function is the code being compared',
                        'no build-time macros or extensions change the supplied function'],
        'trusted_components': ['Python interpreter', 'G0 parser and interval checker',
                               'pycparser and rejecting C adapter'],
        'not_proven': ['checker implementation correctness', 'machine-code equivalence',
                       'external effects', 'business intent'],
        'checker_sha256': implementation_digest(),
        'pycparser_version': pycparser.__version__,
        'python_version': platform.python_version(),
        'c_function': fn.name,
        'partitions_checked': cells,
        'counterexample': counterexample,
    }


def verify(glr_source, c_source):
    result = compare_model(parse(glr_source), parse_c(c_source))
    result['sources'] = {'glr_sha256': digest(glr_source), 'c_sha256': digest(c_source)}
    return result


def lift_project(project, name=None, input_name=None):
    from .c_project import analyze_project
    analysis = analyze_project(project)
    fn = analysis.entry
    return Program(name or fn.name, input_name or fn.parameter,
                   tuple(Rule(lo, hi, value) for lo, hi, value in execute_intervals(fn)))


def verify_project(glr_source, project):
    from .c_project import analyze_project
    analysis = analyze_project(project)
    result = compare_model(parse(glr_source), analysis.entry)
    result['sources'] = {
        'glr_sha256': digest(glr_source),
        'manifest_sha256': digest(project.manifest_text),
        'c_files': [{'path': name, 'sha256': digest(source)} for name, source in project.sources],
    }
    result['project'] = analysis.provenance
    result['assumptions'].append('calls resolve to the provided definitions without link-time symbol substitution')
    result['trusted_components'].append('G0 project loader, declaration binding and constant-call resolver')
    return result


def replay_project(record, glr_source, project):
    return check_record(record, verify_project(glr_source, project))


def replay(record, glr_source, c_source):
    return check_record(record, verify(glr_source, c_source))


def check_record(record, current):
    if not isinstance(record, dict) or record != current:
        raise ReviewError('STALE_RECORD', '현재 소스·검사기와 일치하지 않거나 변경된 검사 기록입니다.')
    if current['status'] != 'equivalent_in_g0_model':
        raise ReviewError('NOT_EQUIVALENT', '이 기록은 모델 동등성 성공 기록이 아닙니다.')
    return current
