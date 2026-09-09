"""Independent multi-translation-unit linking/execution and binding failures."""
import copy
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import unittest

from test_review import ROOT, BUILD, EXAMPLE, temporary, invoke
from ref.geul_review.core import MIN, END, Program, Rule, ReviewError, render, evaluate
from ref.geul_review.codegen import checked_emit_c
from ref.geul_review.c_project import PROJECT_FORMAT, load_project, analyze_project, MAX_CALL_DEPTH
from ref.geul_review.verification import lift_project, verify_project, replay_project

CASES = json.loads((Path(__file__).parent / 'projects.json').read_text(encoding='utf-8'))
NEGATIVE = json.loads((Path(__file__).parent / 'project-negative.json').read_text(encoding='utf-8'))


def create_project(folder, case):
    for label, source in case['sources'].items():
        path = folder / label
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode('utf-8'))
    manifest = folder / 'project.json'
    manifest.write_text(json.dumps({'format': PROJECT_FORMAT, 'entry': case['entry'],
                                    'sources': list(case['sources'])}), encoding='utf-8')
    return manifest


def expected(case):
    return Program('규칙', '입력', tuple(Rule(*row) for row in case['ranges']))


class ProjectTests(unittest.TestCase):
    def test_five_fixed_projects_lift_with_provenance(self):
        self.assertEqual(5, len(CASES))
        for case in CASES:
            with self.subTest(case=case['id']), temporary() as folder:
                project = load_project(create_project(folder, case))
                program = lift_project(project, '규칙', '입력')
                self.assertEqual(expected(case), program)
                result = verify_project(render(program), project)
                self.assertEqual('equivalent_in_g0_model', result['status'])
                self.assertEqual(len(case['sources']), len(result['sources']['c_files']))
                self.assertGreaterEqual(len(result['project']['reachable_functions']), 3)
                self.assertGreaterEqual(len(result['project']['calls']), 2)
                for call in result['project']['calls']:
                    self.assertIn(call['file'], case['sources'])
                    self.assertGreater(call['line'], 0)
                self.assertEqual(result, replay_project(result, render(program), project))

    def test_twenty_fixed_binding_and_purity_failures(self):
        self.assertEqual(20, len(NEGATIVE))
        for case in NEGATIVE:
            with self.subTest(case=case['id']), temporary() as folder:
                project = load_project(create_project(folder, case))
                with self.assertRaises(ReviewError) as error:
                    analyze_project(project)
                self.assertEqual(case['error'], error.exception.code)

    def test_helper_only_change_gives_counterexample_and_invalidates_record(self):
        with temporary() as folder:
            path = create_project(folder, CASES[0])
            project = load_project(path)
            glr = render(expected(CASES[0]))
            record = verify_project(glr, project)
            (folder / 'limits.c').write_text('int free_limit(void) { return 60000; }', encoding='utf-8')
            changed = load_project(path)
            result = verify_project(glr, changed)
            self.assertEqual({'input': 50000, 'glr': 0, 'c': 3000}, result['counterexample'])
            with self.assertRaisesRegex(ReviewError, 'STALE_RECORD'):
                replay_project(record, glr, changed)
            forged = copy.deepcopy(record)
            forged['project']['calls'] = []
            with self.assertRaisesRegex(ReviewError, 'STALE_RECORD'):
                replay_project(forged, glr, project)

    def test_manifest_change_invalidates_record_but_not_meaning(self):
        with temporary() as folder:
            path = create_project(folder, CASES[1])
            project = load_project(path)
            text = render(expected(CASES[1]))
            record = verify_project(text, project)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['sources'].reverse()
            path.write_text(json.dumps(data), encoding='utf-8')
            reordered = load_project(path)
            self.assertEqual('equivalent_in_g0_model', verify_project(text, reordered)['status'])
            with self.assertRaisesRegex(ReviewError, 'STALE_RECORD'):
                replay_project(record, text, reordered)

    def test_manifest_validation_and_file_boundaries(self):
        with temporary() as folder:
            path = create_project(folder, CASES[0])
            original = json.loads(path.read_text(encoding='utf-8'))
            variants = [dict(original, entry='missing space'), dict(original, format='unknown'),
                        dict(original, extra=True), dict(original, sources=[])]
            for source in ('../outside.c', '/outside.c', 'C:/outside.c', './policy.c',
                           'sub//policy.c', 'sub\\policy.c', 'missing.c', 'policy.h'):
                variants.append(dict(original, sources=[source]))
            variants.append(dict(original, sources=['policy.c', 'policy.c']))
            for data in variants:
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.subTest(data=data), self.assertRaises(ReviewError):
                    load_project(path)
            path.write_text('{"format":"x","format":"y","entry":"f","sources":[]}', encoding='utf-8')
            with self.assertRaisesRegex(ReviewError, 'PROJECT'):
                load_project(path)
            # The loader rejects duplicate hard links as well as duplicate spellings.
            os.link(folder / 'policy.c', folder / 'alias.c')
            path.write_text(json.dumps(dict(original, sources=['policy.c', 'alias.c'])), encoding='utf-8')
            with self.assertRaisesRegex(ReviewError, 'PROJECT_PATH'):
                load_project(path)

    def test_depth_limit_applies_even_when_values_are_memoized(self):
        # Sorted names precompute the leaf before parents; memoization must not hide depth.
        count = MAX_CALL_DEPTH + 1
        helpers = ['int helper0(void) { return 1; }']
        for i in range(1, count):
            helpers.append(f'int helper{i-1}(void); int helper{i}(void) {{ return helper{i-1}(); }}')
        case = {'entry': 'root', 'sources': {
            'policy.c': f'int helper{count-1}(void); int root(int x) {{ return helper{count-1}(); }}',
            'helpers.c': '\n'.join(helpers)}}
        with temporary() as folder:
            project = load_project(create_project(folder, case))
            with self.assertRaisesRegex(ReviewError, 'LIMIT'):
                analyze_project(project)

    def test_selected_entry_excludes_unrelated_function_from_call_provenance(self):
        case = copy.deepcopy(CASES[0])
        case['sources']['unrelated.c'] = 'int other(int x) { return 7; }'
        with temporary() as folder:
            analysis = analyze_project(load_project(create_project(folder, case)))
            self.assertIn('other', analysis.provenance['checked_functions'])
            self.assertNotIn('other', [f['name'] for f in analysis.provenance['reachable_functions']])

    def test_project_cli_roundtrip_record_and_input_protection(self):
        with temporary() as folder:
            path = create_project(folder, CASES[0])
            lifted, record = folder / '규칙.glr', folder / 'record.json'
            result = invoke('lift-project', path, '--name', '배송비', '--input-name', '주문금액', '-o', lifted)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(EXAMPLE.read_text(encoding='utf-8'), lifted.read_text(encoding='utf-8'))
            result = invoke('verify-project', lifted, path, '-o', record)
            self.assertEqual(0, result.returncode, result.stderr)
            result = invoke('verify-project', lifted, path, '--record', record)
            self.assertEqual(0, result.returncode, result.stderr)
            original = (folder / 'limits.c').read_bytes()
            result = invoke('lift-project', path, '-o', folder / 'limits.c')
            self.assertEqual(1, result.returncode)
            self.assertEqual('OUTPUT_INPUT', json.loads(result.stderr)['error'])
            self.assertEqual(original, (folder / 'limits.c').read_bytes())
            (folder / 'limits.c').write_text('int free_limit(void) { return 60000; }', encoding='utf-8')
            result = invoke('verify-project', lifted, path)
            self.assertEqual(1, result.returncode)
            self.assertEqual('different', json.loads(result.stdout)['status'])

    def test_native_projects_are_compiled_as_separate_translation_units(self):
        compiler = shutil.which(os.environ.get('CC', 'gcc'))
        self.assertIsNotNone(compiler, 'GCC가 필요합니다.')
        summary = []
        for case in CASES:
            with self.subTest(case=case['id']), temporary() as folder:
                project = load_project(create_project(folder, case))
                program = lift_project(project, '규칙', '입력')
                generated = folder / 'generated.c'
                generated.write_text(checked_emit_c(program), encoding='utf-8')
                runner = folder / 'runner.c'
                runner.write_text('#include <stdio.h>\n#include <limits.h>\n'
                    '_Static_assert(INT_MAX == 2147483647 && INT_MIN == (-2147483647-1), "int32");\n'
                    f'int {case["entry"]}(int); int geul_review(int);\n'
                    'int main(void) { int x; while (scanf("%d", &x) == 1) '
                    f'printf("%d %d\\n", {case["entry"]}(x), geul_review(x)); return 0; }}\n', encoding='utf-8')
                executable = folder / ('run.exe' if os.name == 'nt' else 'run')
                compiled = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', *map(str, project.input_paths[1:]), str(generated), str(runner),
                    '-o', str(executable)], capture_output=True, encoding='utf-8', timeout=60)
                self.assertEqual(0, compiled.returncode, compiled.stderr)
                rng = random.Random(20260908)
                inputs = {MIN, MIN+1, END-2, END-1, -1, 0, 1}
                for lo, hi, value in case['ranges']:
                    inputs.update(v for v in (lo-1, lo, lo+1, hi-1, hi, hi+1) if MIN <= v < END)
                inputs.update(rng.randrange(MIN, END) for _ in range(1000))
                inputs = sorted(inputs)
                expected_values = [next(v for lo, hi, v in case['ranges'] if lo <= x < hi) for x in inputs]
                self.assertEqual(expected_values, [evaluate(program, x) for x in inputs])
                run = subprocess.run([str(executable)], input=''.join(f'{x}\n' for x in inputs),
                                     capture_output=True, encoding='utf-8', timeout=30)
                self.assertEqual(0, run.returncode, run.stderr)
                actual = [tuple(map(int, line.split())) for line in run.stdout.splitlines()]
                self.assertEqual([(v, v) for v in expected_values], actual)
                summary.append({'case': case['id'], 'translation_units': len(project.sources),
                                'inputs': len(inputs), 'mismatches': 0})
        (BUILD / 'project-execution-results.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
