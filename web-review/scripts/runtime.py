"""Freeze/fetch extra source and package provenance for the React oracle.

This script only copies raw source; execution is a separate explicit test.
The main 12-case corpus and its success denominator are unchanged.
"""
import argparse
import json
import re
from corpus import ROOT, PACKAGE, LOCK as CORPUS_LOCK, digest, git, repository, ensure_revision, checked_path

SELECTION = PACKAGE / 'corpus' / 'runtime-selection.json'
LOCK = PACKAGE / 'corpus' / 'runtime-lock.json'
CACHE = ROOT / 'build' / 'web-runtime'


def package_entries(text, selectors):
    result = []
    for selector in selectors:
        pattern = r'^' + re.escape(selector) + r':\r?\n((?:[ \t]+[^\n]*\n)+)'
        matches = re.findall(pattern, text, re.M)
        if len(matches) != 1:
            raise ValueError(f'Expected one exact lock entry: {selector}')
        block = matches[0]
        version = re.search(r'^  version "([^"]+)"', block, re.M).group(1)
        integrity = re.search(r'^  integrity (\S+)', block, re.M).group(1)
        result.append({'name': selector.split('@')[0], 'selector': selector, 'version': version, 'integrity': integrity})
    return result


def main(mode):
    selection_bytes = SELECTION.read_bytes()
    selection = json.loads(selection_bytes)
    corpus_bytes = CORPUS_LOCK.read_bytes()
    corpus = json.loads(corpus_bytes)
    case = next(item for item in corpus['cases'] if item['id'] == selection['case'])
    projects = json.loads((PACKAGE / 'corpus' / 'selection.json').read_text(encoding='utf-8'))['projects']
    if mode == 'freeze':
        if LOCK.exists():
            raise SystemExit('Runtime lock already exists; do not replace pinned evidence.')
        repo = repository(case['project'], projects[case['project']]['url'])
        result = {'schema': 'web-corpus-runtime-lock-1', 'corpusLockSha256': digest(corpus_bytes), 'selectionSha256': digest(selection_bytes), 'case': case['id'], 'revisions': []}
        for revision, commit in [('before', case['parent']), ('after', case['head'])]:
            ensure_revision(repo, commit)
            entry = {'revision': revision, 'commit': commit, 'blobs': []}
            for relative in selection['paths']:
                data = git(repo, 'show', f'{commit}:{relative}')
                blob = git(repo, 'rev-parse', f'{commit}:{relative}').decode().strip()
                target = checked_path(CACHE / case['id'] / revision, relative)
                if target.exists() and target.read_bytes() != data:
                    raise SystemExit(f'Changed cached source: {target}')
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    with target.open('xb') as stream:
                        stream.write(data)
                entry['blobs'].append({'path': relative, 'gitBlob': blob, 'sha256': digest(data), 'bytes': len(data)})
                if relative == 'yarn.lock':
                    entry['packages'] = package_entries(data.decode('utf-8'), selection['packages'])
            result['revisions'].append(entry)
        with LOCK.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    assert lock['corpusLockSha256'] == digest(corpus_bytes)
    assert lock['selectionSha256'] == digest(selection_bytes)
    count = 0
    for entry in lock['revisions']:
        assert entry['commit'] == case['parent' if entry['revision'] == 'before' else 'head']
        for blob in entry['blobs']:
            target = checked_path(CACHE / case['id'] / entry['revision'], blob['path'])
            if mode == 'fetch' and not target.exists():
                repo = repository(case['project'], projects[case['project']]['url'])
                ensure_revision(repo, entry['commit'])
                data = git(repo, 'show', f"{entry['commit']}:{blob['path']}")
                assert digest(data) == blob['sha256']
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(data)
            if not target.exists() or digest(target.read_bytes()) != blob['sha256']:
                raise SystemExit(f'Missing or changed runtime source: {target}')
            if blob['path'] == 'yarn.lock':
                assert package_entries(target.read_text(encoding='utf-8'), selection['packages']) == entry['packages']
            count += 1
    print(json.dumps({'runtimeContexts': len(lock['revisions']), 'verifiedBlobs': count}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['freeze', 'fetch', 'verify'])
    main(parser.parse_args().mode)
