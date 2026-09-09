"""Command-line entry for the experimental G0 language."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from .core import MAX_BYTES, PROFILE, ReviewError, parse, render, evaluate, integer, differences


def read_source(path):
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ReviewError('LIMIT', '파일 크기 한계 1MiB를 넘었습니다.')
    # Preserve CRLF for source hashes; parsing can ignore the spelling of line breaks.
    return data.decode('utf-8')


def write_output(path, text, inputs):
    if path is None:
        print(text, end='' if text.endswith('\n') else '\n')
        return
    output = Path(path)
    for source in inputs:
        source = Path(source)
        if (output.resolve() == source.resolve()
                or output.exists() and source.exists() and os.path.samefile(output, source)):
            raise ReviewError('OUTPUT_INPUT', '출력으로 입력 파일을 덮어쓸 수 없습니다.')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.g0-', suffix='.tmp', dir=output.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(text.encode('utf-8'))
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def as_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def arguments():
    parser = argparse.ArgumentParser(prog='geul-review', description='글 검토 언어 G0: 제한된 정수 결정 규칙')
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check', help='문법·타입·정의역 검사')
    check.add_argument('source')
    run = commands.add_parser('run', help='글을 독립 참조 실행기로 실행')
    run.add_argument('source'); run.add_argument('value')
    emit = commands.add_parser('emit-c', help='G0 모델 전범위 비교 후 C 생성')
    emit.add_argument('source'); emit.add_argument('-o', '--output')
    lift = commands.add_parser('lift-c', help='지원하는 C 결정 규칙을 글로 변환')
    lift.add_argument('source'); lift.add_argument('--name'); lift.add_argument('--input-name')
    lift.add_argument('-o', '--output')
    verify = commands.add_parser('verify-c', help='글과 C의 모델 전범위 비교')
    verify.add_argument('source'); verify.add_argument('c_source')
    verify.add_argument('-o', '--output'); verify.add_argument('--record', help='기존 기록을 현재 파일로 재검사')
    project_lift = commands.add_parser('lift-project', help='여러 C 파일의 결정 규칙과 상수 함수를 글로 변환')
    project_lift.add_argument('project'); project_lift.add_argument('--name'); project_lift.add_argument('--input-name')
    project_lift.add_argument('-o', '--output')
    project_verify = commands.add_parser('verify-project', help='글과 C 프로젝트 진입점의 모델 전범위 비교')
    project_verify.add_argument('source'); project_verify.add_argument('project')
    project_verify.add_argument('-o', '--output'); project_verify.add_argument('--record')
    diff = commands.add_parser('compare', help='글 두 버전의 정확한 변경 입력 구간')
    diff.add_argument('before'); diff.add_argument('after'); diff.add_argument('-o', '--output')
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = arguments().parse_args(argv)
    try:
        if args.command == 'check':
            program = parse(read_source(args.source))
            print(as_json({'status': 'valid_g0', 'profile': PROFILE, 'name': program.name,
                           'rules': len(program.rules)}), end='')
        elif args.command == 'run':
            print(evaluate(parse(read_source(args.source)), integer(args.value)))
        elif args.command == 'emit-c':
            from .codegen import checked_emit_c
            output = checked_emit_c(parse(read_source(args.source)))
            write_output(args.output, output, [args.source])
        elif args.command == 'lift-c':
            from .verification import lift, verify
            source = read_source(args.source)
            output = render(lift(source, args.name, args.input_name))
            if verify(output, source)['status'] != 'equivalent_in_g0_model':
                raise ReviewError('LIFT', '상위 변환 후 모델 동등성 확인에 실패했습니다.')
            write_output(args.output, output, [args.source])
        elif args.command == 'verify-c':
            from .verification import verify, replay
            glr, c = read_source(args.source), read_source(args.c_source)
            inputs = [args.source, args.c_source]
            if args.record:
                record = json.loads(read_source(args.record))
                result = replay(record, glr, c)
                inputs.append(args.record)
            else:
                result = verify(glr, c)
            write_output(args.output, as_json(result), inputs)
            return 0 if result['status'] == 'equivalent_in_g0_model' else 1
        elif args.command == 'lift-project':
            from .c_project import load_project
            from .verification import lift_project, verify_project
            project = load_project(args.project)
            output = render(lift_project(project, args.name, args.input_name))
            if verify_project(output, project)['status'] != 'equivalent_in_g0_model':
                raise ReviewError('LIFT', '프로젝트 상위 변환 후 모델 동등성 확인에 실패했습니다.')
            write_output(args.output, output, project.input_paths)
        elif args.command == 'verify-project':
            from .c_project import load_project
            from .verification import verify_project, replay_project
            project = load_project(args.project)
            source = read_source(args.source)
            inputs = [args.source, *project.input_paths]
            if args.record:
                record = json.loads(read_source(args.record))
                result = replay_project(record, source, project)
                inputs.append(args.record)
            else:
                result = verify_project(source, project)
            write_output(args.output, as_json(result), inputs)
            return 0 if result['status'] == 'equivalent_in_g0_model' else 1
        elif args.command == 'compare':
            result = differences(parse(read_source(args.before)), parse(read_source(args.after)))
            write_output(args.output, as_json({'profile': PROFILE, 'changes': result}), [args.before, args.after])
        return 0
    except ReviewError as e:
        print(as_json({'status': 'unsupported' if e.code.startswith('C_') else 'error',
                       'error': e.code, 'message': e.message, 'line': e.line}), end='', file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        print(as_json({'status': 'error', 'error': 'IO', 'message': str(e)}), end='', file=sys.stderr)
        return 1
    except ImportError:
        print('DEPENDENCY: python -m pip install -r requirements-review.txt', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
