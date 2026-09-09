"""Record every file in each original change, including unselected files.

This is a Git change inventory, not semantic coverage. It does not read a file's
extension as evidence that the file is irrelevant. Rename detection is disabled
so a rename is retained as an explicit delete/add pair.
"""
import argparse
import json
import re
from corpus import PACKAGE, ROOT, LOCK as CORPUS_LOCK, SELECTION, digest, git

LOCK = PACKAGE / 'corpus' / 'change-inventory.lock.json'
RAW_HEADER = re.compile(rb':([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([AMDT])')


def parse_raw(data):
    if not data:
        return []
    fields = data.split(b'\0')
    if fields.pop() != b'' or len(fields) % 2:
        raise ValueError('Malformed NUL-delimited raw Git diff')
    rows = []
    seen = set()
    for index in range(0, len(fields), 2):
        match = RAW_HEADER.fullmatch(fields[index])
        if not match:
            raise ValueError(f'Unsupported raw diff header: {fields[index]!r}')
        before_mode, after_mode, before_blob, after_blob, status = [item.decode('ascii') for item in match.groups()]
        filename = fields[index + 1].decode('utf-8', errors='strict')
        if not filename or filename in seen:
            raise ValueError('Empty or duplicate changed path')
        seen.add(filename)
        rows.append({'path': filename, 'status': status,
                     'beforeMode': before_mode, 'afterMode': after_mode,
                     'beforeBlob': None if before_blob == '0' * 40 else before_blob,
                     'afterBlob': None if after_blob == '0' * 40 else after_blob})
    return rows


def parse_numstat(data):
    if not data:
        return {}
    fields = data.split(b'\0')
    if fields.pop() != b'':
        raise ValueError('Malformed NUL-delimited numstat')
    result = {}
    for field in fields:
        added, removed, encoded_path = field.split(b'\t', 2)
        filename = encoded_path.decode('utf-8', errors='strict')
        if not filename or filename in result:
            raise ValueError('Empty or duplicate numstat path')
        if added == removed == b'-':
            result[filename] = {'addedLines': None, 'removedLines': None, 'binary': True}
        elif added.isdigit() and removed.isdigit():
            result[filename] = {'addedLines': int(added), 'removedLines': int(removed), 'binary': False}
        else:
            raise ValueError('Invalid numstat count')
    return result


def inventory(repo, parent, head, selected_paths):
    options = ['--no-renames', '--no-ext-diff', '--no-textconv']
    raw = parse_raw(git(repo, 'diff-tree', '-r', '--raw', '-z', '--no-abbrev', *options, parent, head))
    numstat = parse_numstat(git(repo, 'diff', '--numstat', '-z', *options, parent, head))
    if {row['path'] for row in raw} != set(numstat):
        raise ValueError('Raw diff and numstat paths disagree')
    selected = set(selected_paths)
    for row in raw:
        row.update(numstat[row['path']])
        row['selectedInCorpus'] = row['path'] in selected
    return {'beforeTree': git(repo, 'rev-parse', parent + '^{tree}').decode().strip(),
            'afterTree': git(repo, 'rev-parse', head + '^{tree}').decode().strip(),
            'changedFiles': raw,
            'selectedUnchangedPaths': sorted(selected - set(numstat))}


def build():
    corpus_bytes = CORPUS_LOCK.read_bytes()
    corpus = json.loads(corpus_bytes)
    selection_bytes = SELECTION.read_bytes()
    if corpus['selectionSha256'] != digest(selection_bytes):
        raise ValueError('Selection differs from frozen corpus')
    selection = json.loads(selection_bytes)
    result = {'schema': 'web-change-inventory-lock-1', 'corpusLockSha256': digest(corpus_bytes),
              'selectionSha256': digest(selection_bytes),
              'scope': 'All changed Git paths between the pinned commits; selection counts are file inventory, not analysis success or semantic coverage.',
              'renamePolicy': 'No rename detection; renames are retained as delete/add paths.', 'cases': []}
    for case in corpus['cases']:
        chosen = next(row for row in selection['cases'] if row['id'] == case['id'])
        repo = ROOT / 'build' / 'research' / case['project']
        entry = {'case': case['id'], 'project': case['project'], 'parent': case['parent'], 'head': case['head'],
                 **inventory(repo, case['parent'], case['head'], chosen['paths'])}
        for row in entry['changedFiles']:
            if not row['selectedInCorpus']:
                continue
            for revision, field in [('before', 'beforeBlob'), ('after', 'afterBlob')]:
                selected_blob = next((blob for blob in case['blobs'] if blob['revision'] == revision and blob['path'] == row['path']), None)
                if row[field] is not None and (selected_blob is None or selected_blob['gitBlob'] != row[field]):
                    raise ValueError('Selected file differs from original changed blob')
        result['cases'].append(entry)
    return result


def main(mode):
    current = build()
    if mode == 'freeze':
        with LOCK.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(current, ensure_ascii=False, indent=2) + '\n')
    frozen = json.loads(LOCK.read_text(encoding='utf-8'))
    if frozen != current:
        raise ValueError('Original change inventory differs from its frozen record')
    lines = ['# 원본 변경 파일의 포함 범위', '',
             '고정한 원본 커밋의 전체 변경 파일과 기존 분석용 선택 파일을 대조한다. 파일을 가져온 사실은 그 동작을 해석한 사실이 아니다. 선택 파일의 수를 의미 보존 성공률로 사용하지 않는다.', '',
             '| 사례 | 전체 변경 파일 | 선택한 변경 파일 | 선택 밖 변경 파일 |',
             '|---|---:|---:|---:|']
    total = selected_count = omitted_count = 0
    for case in current['cases']:
        count = len(case['changedFiles'])
        selected = sum(row['selectedInCorpus'] for row in case['changedFiles'])
        total += count
        selected_count += selected
        omitted_count += count - selected
        lines.append(f"| {case['case']} | {count} | {selected} | {count - selected} |")
    for case in current['cases']:
        lines.extend(['', f"## {case['case']}", '', f"원본: `{case['parent']}` → `{case['head']}`", ''])
        for row in case['changedFiles']:
            status = '선택에 포함' if row['selectedInCorpus'] else '선택 밖'
            count = 'binary' if row['binary'] else f"+{row['addedLines']}/-{row['removedLines']}"
            lines.append(f"- {status}: `{row['path']}` ({row['status']}, {count})")
        if case['selectedUnchangedPaths']:
            lines.extend(['', '원본 연결을 위해 선택했으나 이 커밋에서 내용이 바뀌지 않은 파일:',
                          *[f'- `{name}`' for name in case['selectedUnchangedPaths']]])
    summary = {'schema': 'web-change-inventory-results-1', 'inventorySha256': digest(LOCK.read_bytes()),
               'cases': len(current['cases']), 'changedFileOccurrences': total,
               'selectedChangedFileOccurrences': selected_count, 'unselectedChangedFileOccurrences': omitted_count,
               'wholeBehaviorCasesVerified': 0, 'semanticCoverage': None,
               'scope': current['scope']}
    output = ROOT / 'build' / 'web-review'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'change-inventory.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (output / 'change-inventory-results.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['freeze', 'verify'])
    main(parser.parse_args().mode)
