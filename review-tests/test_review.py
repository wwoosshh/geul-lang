"""Fixed public development corpus, counterexamples and independent GCC execution.

GCC absence is an error, never a skipped successful test. No production compiler
or source file is modified by these tests. All generated artifacts stay in build/.
"""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ref.geul_review.core import (MIN, END, MAX_RULES, Program, Rule, ReviewError,
                                 parse, render, normalize, evaluate, differences)
from ref.geul_review.c_model import parse_c, execute_intervals
from ref.geul_review.codegen import checked_emit_c
from ref.geul_review.verification import verify, replay, lift

CASES = json.loads((Path(__file__).parent / 'positive.json').read_text(encoding='utf-8'))
NEGATIVE = json.loads((Path(__file__).parent / 'negative.json').read_text(encoding='utf-8'))
EXAMPLE = ROOT / 'examples' / 'review' / '배송비.glr'
BUILD = ROOT / 'build' / 'review-tests'


def expected_program(case):
    return Program('규칙', '입력', tuple(Rule(*row) for row in case['ranges']))


def invoke(*args):
    return subprocess.run([sys.executable, str(ROOT / 'build.py'), 'review', *map(str, args)],
                          capture_output=True, encoding='utf-8', cwd=ROOT, timeout=30)


@contextmanager
def temporary():
    BUILD.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='case-', dir=BUILD) as directory:
        path = Path(directory).resolve()
        if not path.is_relative_to(BUILD.resolve()):
            raise RuntimeError('test workspace escaped build/review-tests')
        yield path


class ModelTests(unittest.TestCase):
    def test_fixed_corpus_has_twenty_distinct_positive_and_negative_cases(self):
        self.assertEqual(20, len(CASES))
        self.assertEqual(20, len(NEGATIVE))
        self.assertEqual(20, len({case['id'] for case in CASES}))
        self.assertEqual(20, len({case['id'] for case in NEGATIVE}))

    def test_positive_models_and_bidirectional_roundtrip(self):
        for case in CASES:
            with self.subTest(case=case['id']):
                expected = expected_program(case)
                model = execute_intervals(parse_c(case['c']))
                self.assertEqual(case['ranges'], [list(row) for row in model])
                extracted = lift(case['c'], '규칙', '입력')
                self.assertEqual(expected, extracted)
                text = render(expected)
                self.assertEqual(expected, parse(text))
                self.assertEqual('equivalent_in_g0_model', verify(text, case['c'])['status'])
                emitted = checked_emit_c(parse(text))
                self.assertEqual('equivalent_in_g0_model', verify(text, emitted)['status'])
                self.assertEqual(expected.rules, lift(emitted).rules)

    def test_fixed_negative_corpus_is_rejected_with_expected_error(self):
        for case in NEGATIVE:
            with self.subTest(case=case['id']):
                with self.assertRaises(ReviewError) as caught:
                    if case['kind'] == 'c':
                        execute_intervals(parse_c(case['source']))
                    else:
                        parse(case['source'])
                self.assertEqual(case['error'], caught.exception.code)

    def test_wrong_c_is_detected_for_every_corpus_program(self):
        for case in CASES:
            with self.subTest(case=case['id']):
                changed = re.sub(r'return\s+[^;]+;', 'return 123456;', case['c'])
                record = verify(render(expected_program(case)), changed)
                self.assertEqual('different', record['status'])
                self.assertEqual(MIN, record['counterexample']['input'])
                self.assertEqual(123456, record['counterexample']['c'])

    def test_single_input_regression_has_exact_counterexample(self):
        text = EXAMPLE.read_text(encoding='utf-8')
        c = (EXAMPLE.parent / '배송비.c').read_text(encoding='utf-8')
        result = verify(text, c.replace('>= 50000', '> 50000'))
        self.assertEqual({'input': 50000, 'glr': 0, 'c': 3000}, result['counterexample'])
        extreme = expected_program(CASES[14])
        result = verify(render(extreme), 'int f(int x) { return 0; }')
        self.assertEqual(MIN, result['counterexample']['input'])

    def test_every_comparison_at_integer_boundaries(self):
        import operator
        comparisons = {'<': operator.lt, '<=': operator.le, '>': operator.gt,
                       '>=': operator.ge, '==': operator.eq, '!=': operator.ne}
        for threshold in (MIN, MIN + 1, -1, 0, 1, END - 2, END - 1):
            samples = {MIN, MIN + 1, END - 2, END - 1, -2, -1, 0, 1, 2}
            samples.update(x for x in (threshold-1, threshold, threshold+1) if MIN <= x < END)
            for op, function in comparisons.items():
                for reverse in (False, True):
                    condition = f'{threshold} {op} x' if reverse else f'x {op} {threshold}'
                    c = f'int f(int x) {{ if ({condition}) return 1; return 0; }}'
                    ranges = execute_intervals(parse_c(c))
                    for x in samples:
                        actual = next(value for lo, hi, value in ranges if lo <= x < hi)
                        expected = int(function(threshold, x) if reverse else function(x, threshold))
                        self.assertEqual(expected, actual, (condition, x))

    def test_record_replay_and_tampering(self):
        text = EXAMPLE.read_text(encoding='utf-8')
        c = checked_emit_c(parse(text))
        record = verify(text, c)
        self.assertEqual(record, replay(record, text, c))
        for key, changed in [('status', 'different'), ('partitions_checked', 999),
                             ('checker_sha256', '0'*64), ('counterexample', {'input': 0})]:
            modified = copy.deepcopy(record)
            modified[key] = changed
            with self.subTest(field=key), self.assertRaisesRegex(ReviewError, 'STALE_RECORD'):
                replay(modified, text, c)
        for changed_text, changed_c in [(text + '\n', c), (text, c + '/* change */'),
                                        (text.replace('\n', '\r\n'), c)]:
            with self.assertRaisesRegex(ReviewError, 'STALE_RECORD'):
                replay(record, changed_text, changed_c)
        wrong = verify(text, 'int f(int x) { return 0; }')
        wrong['status'], wrong['counterexample'] = 'equivalent_in_g0_model', None
        with self.assertRaisesRegex(ReviewError, 'STALE_RECORD'):
            replay(wrong, text, 'int f(int x) { return 0; }')

    def test_no_unknown_effects_even_in_dead_branches(self):
        bad_sources = [
            'int f(int x) { if (x > 2147483647) return external(); return 0; }',
            'int f(int x) { return 0; external(); }',
            'int f(int x) { return; }',
            'int f(int x) { return "//not a comment"; }',
            'int f(int x) { return 0xff; }',
            'int f(int x) { return 1U; }',
            'int f(int x) { return (int) 1; }',
            'int f(int x) { return -2147483649; }',
            'int f(volatile int x) { return 0; }',
            'static int f(int x) { return 0; }',
            'int f(int __LINE__) { return 0; }',
            'int __func__(int x) { return 0; }',
            'int f(int x) { // keep reading\\\n return 1;\n return 0; }',
            'int f(int x) { // trigraph ??/\n return 1;\n return 0; }',
        ]
        for source in bad_sources:
            with self.subTest(source=source), self.assertRaises(ReviewError):
                parse_c(source)

    def test_reject_malformed_and_incomplete_c(self):
        for source in ['int f(int x) {', '/* unclosed', 'int f(int x) {}',
                       'int f(int x) { if (x < 0) {} else return 1; }']:
            with self.subTest(source=source), self.assertRaises(ReviewError):
                execute_intervals(parse_c(source))

    def test_rule_invariants_and_input_type(self):
        for args in [(MIN, MIN, 0), (MIN-1, END, 0), (MIN, END, END),
                     (MIN, END, True), (MIN, END, 0.0)]:
            with self.subTest(args=args), self.assertRaises(ReviewError):
                Rule(*args)
        for rules in [(), (Rule(0, END, 0),), (Rule(MIN, 0, 0),),
                      (Rule(MIN, 1, 0), Rule(0, END, 1))]:
            with self.subTest(rules=rules), self.assertRaises(ReviewError):
                Program('규칙', '입력', rules)
        p = expected_program(CASES[0])
        for x in (MIN-1, END, True, 0.0, '1'):
            with self.subTest(input=x), self.assertRaisesRegex(ReviewError, 'INT32'):
                evaluate(p, x)

    def test_nfc_and_integer_spelling(self):
        source = EXAMPLE.read_text(encoding='utf-8')
        with self.assertRaisesRegex(ReviewError, 'NFC'):
            parse(unicodedata.normalize('NFD', source))
        for text in ('01', '-0', '+1', '１２', '1'*200):
            invalid = '「규칙」는 부호 있는 32비트 정수 「입력」으로 결정한다.\n'
            invalid += f'「입력」이 모든 범위이면 {text}을 돌려준다.'
            with self.subTest(integer=text), self.assertRaisesRegex(ReviewError, 'INTEGER'):
                parse(invalid)

    def test_analysis_limits_are_errors(self):
        text = EXAMPLE.read_text(encoding='utf-8').splitlines()[0] + '\n'
        text += '「주문금액」이 모든 범위이면 0을 돌려준다.\n' * (MAX_RULES + 1)
        with self.assertRaisesRegex(ReviewError, 'LIMIT'):
            parse(text)
        c = 'int f(int x) {' + 'if (x < 0) {' * 80 + 'return 1;' + '}' * 80 + 'return 0;}'
        with self.assertRaises(ReviewError):
            parse_c(c)

    def test_semantic_diff_ignores_names_and_redundant_ranges(self):
        p = Program('앞', '입력', (Rule(MIN, 0, 7), Rule(0, END, 7)))
        q = Program('뒤', '다른입력', (Rule(MIN, END, 7),))
        self.assertEqual([], differences(p, q))
        self.assertEqual(1, len(normalize(p).rules))
        self.assertEqual(normalize(p), parse(render(p)))

    def test_changed_shipping_interval_and_extreme_singletons(self):
        before = parse(EXAMPLE.read_text(encoding='utf-8'))
        after = parse((EXAMPLE.parent / '배송비-수정.glr').read_text(encoding='utf-8'))
        self.assertEqual([{'minimum': 50000, 'maximum': 59999, 'before': 0, 'after': 3000}],
                         differences(before, after))
        zero = Program('영', '입력', (Rule(MIN, END, 0),))
        at_min = expected_program(CASES[14])
        self.assertEqual([{'minimum': MIN, 'maximum': MIN, 'before': 0, 'after': 1}],
                         differences(zero, at_min))


class CommandTests(unittest.TestCase):
    def test_cli_run_and_meaning_diff(self):
        run = invoke('run', EXAMPLE, '55000')
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual('0\n', run.stdout)
        diff = invoke('compare', EXAMPLE, EXAMPLE.parent / '배송비-수정.glr')
        self.assertEqual(0, diff.returncode, diff.stderr)
        self.assertEqual(50000, json.loads(diff.stdout)['changes'][0]['minimum'])
        self.assertEqual(2, invoke('unknown-command').returncode)

    def test_emit_verify_replay_and_reject_overwrite(self):
        with temporary() as folder:
            source, output, record = folder / '입력.glr', folder / '출력.c', folder / '검사.json'
            source.write_bytes(EXAMPLE.read_bytes())
            result = invoke('emit-c', source, '-o', output)
            self.assertEqual(0, result.returncode, result.stderr)
            result = invoke('verify-c', source, output, '-o', record)
            self.assertEqual(0, result.returncode, result.stderr)
            result = invoke('verify-c', source, output, '--record', record)
            self.assertEqual(0, result.returncode, result.stderr)
            original = source.read_bytes()
            result = invoke('emit-c', source, '-o', source)
            self.assertEqual(1, result.returncode)
            self.assertEqual('OUTPUT_INPUT', json.loads(result.stderr)['error'])
            self.assertEqual(original, source.read_bytes())
            output.write_text('int f(int x) { return 123456; }', encoding='utf-8')
            result = invoke('verify-c', source, output)
            self.assertEqual(1, result.returncode)
            self.assertEqual('different', json.loads(result.stdout)['status'])
            result = invoke('verify-c', source, output, '--record', record)
            self.assertEqual(1, result.returncode)
            self.assertEqual('STALE_RECORD', json.loads(result.stderr)['error'])

    def test_failure_does_not_publish_or_truncate_output(self):
        with temporary() as folder:
            source, output = folder / '입력.glr', folder / '출력.c'
            source.write_text('잘못된 문장', encoding='utf-8')
            output.write_bytes(b'keep this output')
            result = invoke('emit-c', source, '-o', output)
            self.assertEqual(1, result.returncode)
            self.assertEqual(b'keep this output', output.read_bytes())
            self.assertEqual([], list(folder.glob('.g0-*')))


class NativeExecutionTests(unittest.TestCase):
    def test_all_twenty_originals_and_generated_programs_with_gcc(self):
        compiler = shutil.which(os.environ.get('CC', 'gcc'))
        self.assertIsNotNone(compiler, 'GCC가 필요합니다. CC에는 컴파일러 실행 파일 경로만 지정하세요.')
        # Additional regression, without changing the fixed public corpus.
        regression = {'id': 'bare-cr-comments',
                      'c': 'int f(int x) { // comment\r if (x > 0) return 7;\r return 9;\r}',
                      'ranges': [[MIN, 1, 9], [1, END, 7]]}
        execution_cases = CASES + [regression]
        with temporary() as folder:
            parts = ['#include <stdio.h>', '#include <limits.h>',
                     '_Static_assert(INT_MAX == 2147483647 && INT_MIN == (-2147483647-1), "G0 int32 ABI");']
            requests, expected = [], []
            rng = random.Random(20260908)
            for index, case in enumerate(execution_cases):
                program = expected_program(case)
                self.assertEqual(program.rules, lift(case['c']).rules)
                original = re.sub(r'\bint f\(', f'int original_{index}(', case['c'], count=1)
                generated = checked_emit_c(program).replace('geul_review(', f'generated_{index}(')
                parts.extend([original, generated])
                samples = {MIN, MIN+1, END-2, END-1, -1, 0, 1}
                for lo, hi, _ in case['ranges']:
                    samples.update(x for x in (lo-1, lo, lo+1, hi-1, hi, hi+1) if MIN <= x < END)
                samples.update(rng.randrange(MIN, END) for _ in range(1000))
                for x in sorted(samples):
                    truth = next(v for lo, hi, v in case['ranges'] if lo <= x < hi)
                    self.assertEqual(truth, evaluate(program, x))
                    requests.append(f'{index} {x}\n')
                    expected.append((truth, truth))
            parts.append('int main(void) { int id, x; while (scanf("%d %d", &id, &x) == 2) { switch (id) {')
            for index in range(len(execution_cases)):
                parts.append(f'case {index}: printf("%d %d\\n", original_{index}(x), generated_{index}(x)); break;')
            parts.append('default: return 2; } } return 0; }')
            source = folder / 'differential.c'
            executable = folder / ('differential.exe' if os.name == 'nt' else 'differential')
            source.write_text('\n'.join(parts), encoding='utf-8')
            compiled = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                       '-Wno-error=misleading-indentation',
                                       '-Wno-unused-parameter', str(source), '-o', str(executable)],
                                      capture_output=True, encoding='utf-8', timeout=60)
            self.assertEqual(0, compiled.returncode, compiled.stderr)
            executed = subprocess.run([str(executable)], input=''.join(requests), capture_output=True,
                                      encoding='utf-8', timeout=30)
            self.assertEqual(0, executed.returncode, executed.stderr)
            actual = [tuple(map(int, line.split())) for line in executed.stdout.splitlines()]
            self.assertEqual(expected, actual)
            result = {'scope': 'G0 public development corpus; not a holdout or compiler proof',
                      'fixed_programs': len(CASES), 'regression_programs': 1, 'inputs': len(requests),
                      'comparisons': ['handwritten expectations', 'G0 interpreter', 'original C', 'generated C'],
                      'mismatches': 0, 'seed': 20260908}
            (BUILD / 'execution-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                         encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
