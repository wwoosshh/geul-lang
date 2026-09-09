"""Freeze/fetch raw upstream blobs; never install or execute upstream code.

freeze is an explicit maintainer operation after reviewing selection.json.
fetch and verify use the existing lock and cannot silently update it.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
SELECTION = PACKAGE / 'corpus' / 'selection.json'
LOCK = PACKAGE / 'corpus' / 'lock.json'
CACHE = ROOT / 'build' / 'web-corpus'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), '-c', f'safe.directory={repo.as_posix()}', *args], timeout=180)


def repository(name, url):
    repo = ROOT / 'build' / 'research' / name
    if not (repo / '.git').exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--depth=1', '--filter=blob:none', '--no-checkout', url, str(repo)], check=True, timeout=180)
    return repo


def ensure_revision(repo, commit):
    probe = subprocess.run(['git', '-C', str(repo), '-c', f'safe.directory={repo.as_posix()}', 'cat-file', '-e', commit], capture_output=True)
    if probe.returncode:
        git(repo, 'fetch', '--depth=2', 'origin', commit)


def checked_path(base, relative):
    result = (base / relative).resolve()
    if not result.is_relative_to(base.resolve()) or result == base.resolve():
        raise ValueError(f'Path outside corpus cache: {relative}')
    return result


def save_blob(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def freeze(selection):
    if LOCK.exists():
        raise SystemExit('Lock already exists; edit/review a new corpus version rather than silently replacing it.')
    result = {'schema': 'web-corpus-lock-1', 'selectionSha256': digest(SELECTION.read_bytes()), 'cases': []}
    for case in selection['cases']:
        project = selection['projects'][case['project']]
        repo = repository(case['project'], project['url'])
        head = git(repo, 'rev-parse', case['head']).decode().strip()
        parent = git(repo, 'rev-parse', head + '^').decode().strip()
        entry = {'id': case['id'], 'project': case['project'], 'head': head, 'parent': parent, 'blobs': []}
        for revision, commit in [('before', parent), ('after', head)]:
            for relative in [*case['paths'], project['license']]:
                data = git(repo, 'show', f'{commit}:{relative}')
                blob = git(repo, 'rev-parse', f'{commit}:{relative}').decode().strip()
                entry['blobs'].append({'revision': revision, 'path': relative, 'gitBlob': blob, 'sha256': digest(data), 'bytes': len(data)})
                save_blob(checked_path(CACHE / case['id'] / revision, relative), data)
        result['cases'].append(entry)
        print(f"frozen {case['id']}: {len(entry['blobs'])} blobs", flush=True)
    LOCK.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def restore_or_verify(selection, fetch):
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    if lock['selectionSha256'] != digest(SELECTION.read_bytes()):
        raise SystemExit('Selection differs from its frozen digest.')
    total = 0
    for case in lock['cases']:
        for blob in case['blobs']:
            target = checked_path(CACHE / case['id'] / blob['revision'], blob['path'])
            if fetch and not target.exists():
                repo = repository(case['project'], selection['projects'][case['project']]['url'])
                commit = case['parent' if blob['revision'] == 'before' else 'head']
                # Old pinned commits need not be in a shallow clone's current history.
                ensure_revision(repo, commit)
                data = git(repo, 'show', f"{commit}:{blob['path']}")
                if digest(data) != blob['sha256']:
                    raise SystemExit(f'Upstream hash mismatch: {target}')
                save_blob(target, data)
            if not target.exists() or digest(target.read_bytes()) != blob['sha256']:
                raise SystemExit(f'Missing or changed blob: {target}; use fetch for missing blobs.')
            total += 1
    print(json.dumps({'cases': len(lock['cases']), 'projects': len({c['project'] for c in lock['cases']}), 'verifiedBlobs': total}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['freeze', 'fetch', 'verify'])
    args = parser.parse_args()
    selection = json.loads(SELECTION.read_text(encoding='utf-8'))
    if args.mode == 'freeze':
        freeze(selection)
    else:
        restore_or_verify(selection, args.mode == 'fetch')
