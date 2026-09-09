"""Closed C source bundles with checked constant-helper calls.

Files stay separate translation units. This is not C preprocessing or linking:
only explicit int prototypes/definitions and pure zero-argument helpers enter.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re

from .core import MAX_BYTES, ReviewError
from .c_model import (CFunction, parse_c_ast, function_signature, c_literal,
                      decision_function, execute_intervals, unsupported)

PROJECT_FORMAT = 'geul-g0-c-project/v1'
MAX_FILES = 32
MAX_PROJECT_BYTES = 4 * MAX_BYTES
MAX_FUNCTIONS = 128
MAX_CALL_DEPTH = 32


@dataclass(frozen=True)
class ProjectSources:
    entry: str
    manifest_text: str
    sources: tuple[tuple[str, str], ...]
    input_paths: tuple[Path, ...]


@dataclass(frozen=True)
class ProjectAnalysis:
    entry: CFunction
    provenance: dict


@dataclass(frozen=True)
class Definition:
    node: object
    file: str
    parameter: str | None
    visible: frozenset[str]


def read_text(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ReviewError('LIMIT', '파일 크기 한계 1MiB를 넘었습니다.')
    return raw.decode('utf-8')


def load_project(manifest_path):
    """Load only explicitly named .c files beneath the manifest directory."""
    manifest_path = Path(manifest_path).resolve()
    text = read_text(manifest_path)

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReviewError('PROJECT', f'중복된 프로젝트 필드입니다: {key}')
            result[key] = value
        return result

    try:
        manifest = json.loads(text, object_pairs_hook=unique_keys)
    except (json.JSONDecodeError, RecursionError) as e:
        raise ReviewError('PROJECT', '프로젝트 JSON 형식이 잘못됐습니다.') from e
    if (not isinstance(manifest, dict) or set(manifest) != {'format', 'entry', 'sources'}
            or manifest['format'] != PROJECT_FORMAT):
        raise ReviewError('PROJECT', 'format, entry, sources 필드가 있는 G0 C 프로젝트가 필요합니다.')
    entry, labels = manifest['entry'], manifest['sources']
    if not isinstance(entry, str) or re.fullmatch(r'[A-Za-z][A-Za-z_0-9]*', entry) is None:
        raise ReviewError('PROJECT', 'entry는 ASCII C 함수 이름이어야 합니다.')
    if not isinstance(labels, list) or not 1 <= len(labels) <= MAX_FILES:
        raise ReviewError('LIMIT', f'C 파일은 1~{MAX_FILES}개여야 합니다.')
    base = manifest_path.parent
    sources, paths = [], []
    total_bytes = 0
    for label in labels:
        if (not isinstance(label, str) or not label or '\\' in label or ':' in label
                or label.startswith('/') or any(p in ('', '.', '..') for p in label.split('/'))
                or not label.endswith('.c')):
            raise ReviewError('PROJECT_PATH', 'sources에는 프로젝트 안의 상대 .c 경로를 /로 적습니다.')
        path = (base / label).resolve()
        if not path.is_relative_to(base):
            raise ReviewError('PROJECT_PATH', '프로젝트 경계를 벗어나는 파일입니다.')
        if not path.is_file():
            raise ReviewError('PROJECT_PATH', f'C 파일이 없습니다: {label}')
        if any(path == old or os.path.samefile(path, old) for old in paths):
            raise ReviewError('PROJECT_PATH', f'중복된 C 파일입니다: {label}')
        source = read_text(path)
        total_bytes += len(source.encode('utf-8'))
        if total_bytes > MAX_PROJECT_BYTES:
            raise ReviewError('LIMIT', '프로젝트 소스 합계 4MiB를 넘었습니다.')
        sources.append((label, source))
        paths.append(path)
    return ProjectSources(entry, text, tuple(sources), (manifest_path, *paths))


def analyze_project(project):
    from pycparser import c_ast as A

    signatures, definitions = {}, {}
    for label, source in project.sources:
        unit = parse_c_ast(source, filename=label)
        visible = set()
        for top in unit.ext:
            is_definition = isinstance(top, A.FuncDef)
            decl = top.decl if is_definition else top
            if is_definition and top.param_decls:
                unsupported(f'{label}: 옛 형식 함수 정의는 지원하지 않습니다.', code='C_SIGNATURE')
            try:
                parameter = function_signature(decl, definition=is_definition)
            except ReviewError as e:
                raise ReviewError(e.code, f'{label}: {e.message}', e.line) from e
            name, arity = decl.name, int(parameter is not None)
            if name in signatures and signatures[name] != arity:
                unsupported(f'{label}: 선언과 정의의 타입이 다릅니다: {name}', decl.coord, 'C_SIGNATURE')
            signatures[name] = arity
            if len(signatures) > MAX_FUNCTIONS:
                unsupported('프로젝트 함수 개수 한계를 넘었습니다.', code='LIMIT')
            visible.add(name)  # A function's own name is visible in its body.
            if is_definition:
                if name in definitions:
                    unsupported(f'{label}: 함수가 중복 정의됐습니다: {name}', decl.coord, 'C_DUPLICATE')
                definitions[name] = Definition(top, label, parameter, frozenset(visible))
    if project.entry not in definitions or signatures.get(project.entry) != 1:
        unsupported('entry는 int 입력 하나를 받는 정의된 함수여야 합니다.', code='C_ENTRY')
    missing = sorted(set(signatures) - set(definitions))
    if missing:
        unsupported('정의가 없는 외부 함수입니다: ' + ', '.join(missing), code='C_UNRESOLVED')

    constants, constant_depths, active, calls = {}, {}, [], set()

    def call_value(caller, node):
        definition = definitions[caller]
        if not isinstance(node.name, A.ID) or node.args is not None:
            unsupported(f'{definition.file}: 인자 없는 직접 함수 호출만 지원합니다.', node.coord, 'C_CALL')
        callee = node.name.name
        if definition.parameter == callee:
            unsupported(f'{definition.file}: 입력 이름이 함수 이름을 가립니다: {callee}', node.coord, 'C_CALL')
        if callee not in definition.visible:
            unsupported(f'{definition.file}: 호출 전에 보이는 선언이 없습니다: {callee}', node.coord, 'C_CALL_DECL')
        if signatures.get(callee) != 0 or callee not in definitions:
            unsupported(f'{definition.file}: 호출 대상은 int 함수(void)여야 합니다: {callee}', node.coord, 'C_CALL')
        calls.add((caller, callee, definition.file, node.coord.line, node.coord.column))
        return constant_value(callee)

    def constant_value(name):
        if name in constants:
            return constants[name]
        if name in active:
            unsupported('재귀 상수 호출입니다: ' + ' -> '.join(active + [name]), code='C_RECURSION')
        if len(active) >= MAX_CALL_DEPTH:
            unsupported('상수 호출 깊이 한계를 넘었습니다.', code='LIMIT')
        definition = definitions[name]
        items = definition.node.body.block_items or []
        if len(items) != 1 or not isinstance(items[0], A.Return):
            unsupported(f'{definition.file}: 상수 함수 {name}에는 반환문 하나만 허용합니다.',
                        definition.node.coord, 'C_CONSTANT')
        active.append(name)
        try:
            expression = items[0].expr
            value = call_value(name, expression) if isinstance(expression, A.FuncCall) else c_literal(expression)
            depth = 1 + (constant_depths[expression.name.name] if isinstance(expression, A.FuncCall) else 0)
            if depth > MAX_CALL_DEPTH:
                unsupported('상수 호출 깊이 한계를 넘었습니다.', code='LIMIT')
            constants[name] = value
            constant_depths[name] = depth
            return value
        finally:
            active.pop()

    # Validate every provided definition, even ones outside the selected entry.
    for name in sorted(definitions):
        if signatures[name] == 0:
            constant_value(name)
    decisions = {}
    for name in sorted(definitions):
        if signatures[name] == 1:
            fn = decision_function(definitions[name].node, lambda node, caller=name: call_value(caller, node))
            execute_intervals(fn)  # Reject gaps in every supplied decision function.
            decisions[name] = fn

    reachable = {project.entry}
    pending = [project.entry]
    while pending:
        caller = pending.pop()
        for a, b, *_ in calls:
            if a == caller and b not in reachable:
                reachable.add(b)
                pending.append(b)
    provenance = {
        'format': PROJECT_FORMAT,
        'entry': project.entry,
        'checked_functions': sorted(definitions),
        'reachable_functions': [
            {'name': name, 'file': definitions[name].file,
             'line': definitions[name].node.decl.coord.line,
             'parameters': signatures[name],
             **({'constant': constants[name]} if name in constants else {})}
            for name in sorted(reachable)
        ],
        'calls': [{'caller': a, 'callee': b, 'file': file, 'line': line, 'column': column}
                  for a, b, file, line, column in sorted(calls) if a in reachable],
    }
    return ProjectAnalysis(decisions[project.entry], provenance)
