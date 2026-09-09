"""Pin config/package data and the tracked path inventory at corpus revisions."""
import argparse
import json
from corpus import PACKAGE, ROOT, digest, git, repository, checked_path, save_blob, ensure_revision

LOCK = PACKAGE / 'corpus' / 'context-lock.json'
CACHE = ROOT / 'build' / 'web-context'
METADATA = {
    'excalidraw': ('tsconfig.json', ['tsconfig.json', 'package.json', 'packages/excalidraw/package.json']),
    'jitsi-meet': ('tsconfig.web.json', ['tsconfig.web.json', 'package.json']),
    'actual': ('packages/desktop-client/tsconfig.json', ['tsconfig.json', 'package.json', 'packages/desktop-client/tsconfig.json', 'packages/desktop-client/package.json']),
}


def run(mode):
    corpus_bytes = (PACKAGE / 'corpus/lock.json').read_bytes()
    corpus = json.loads(corpus_bytes)
    selection = json.loads((PACKAGE / 'corpus/selection.json').read_text(encoding='utf-8'))
    audit = json.loads((PACKAGE / 'corpus/dependency-audit.json').read_text(encoding='utf-8'))
    if mode == 'freeze':
        if LOCK.exists():
            raise SystemExit('Context lock already exists.')
        result = {'schema': 'web-context-lock-1', 'corpusLockSha256': digest(corpus_bytes), 'contexts': []}
        for case_id in dict.fromkeys(edge['case'] for edge in audit['cases']):
            case = next(c for c in corpus['cases'] if c['id'] == case_id)
            repo = repository(case['project'], selection['projects'][case['project']]['url'])
            config, metadata = METADATA[case['project']]
            for revision in ['before', 'after']:
                commit = case['parent' if revision == 'before' else 'head']
                tree = git(repo, 'ls-tree', '-r', '-z', commit)
                inventory = []
                for item in tree.split(b'\0'):
                    if not item:
                        continue
                    info, filename = item.split(b'\t', 1)
                    filemode, kind, blob = info.decode('ascii').split()
                    inventory.append({'path': filename.decode('utf-8'), 'mode': filemode, 'type': kind, 'blob': blob})
                data = (json.dumps(inventory, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
                base = CACHE / case_id / revision
                save_blob(base / 'inventory.json', data)
                entry = {'case': case_id, 'project': case['project'], 'revision': revision, 'commit': commit, 'configPath': config, 'inventorySha256': digest(data), 'metadata': []}
                for relative in metadata:
                    data = git(repo, 'show', f'{commit}:{relative}')
                    save_blob(checked_path(base / 'files', relative), data)
                    entry['metadata'].append({'path': relative, 'sha256': digest(data)})
                result['contexts'].append(entry)
                print(f'context {case_id} {revision}: {len(inventory)} tracked paths', flush=True)
        LOCK.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return
    result = json.loads(LOCK.read_text(encoding='utf-8'))
    if result['corpusLockSha256'] != digest(corpus_bytes):
        raise SystemExit('Corpus lock changed.')
    for context in result['contexts']:
        base = CACHE / context['case'] / context['revision']
        inventory_file = base / 'inventory.json'
        if mode == 'fetch' and not inventory_file.exists():
            repo = repository(context['project'], selection['projects'][context['project']]['url'])
            ensure_revision(repo, context['commit'])
            tree = git(repo, 'ls-tree', '-r', '-z', context['commit'])
            entries = []
            for item in tree.split(b'\0'):
                if item:
                    info, name = item.split(b'\t', 1)
                    filemode, kind, blob = info.decode('ascii').split()
                    entries.append({'path': name.decode('utf-8'), 'mode': filemode, 'type': kind, 'blob': blob})
            data = (json.dumps(entries, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            if digest(data) != context['inventorySha256']:
                raise SystemExit('Inventory hash mismatch.')
            save_blob(inventory_file, data)
        if not inventory_file.exists() or digest(inventory_file.read_bytes()) != context['inventorySha256']:
            raise SystemExit(f'Missing or modified inventory: {inventory_file}')
        for metadata in context['metadata']:
            target = checked_path(base / 'files', metadata['path'])
            if mode == 'fetch' and not target.exists():
                repo = repository(context['project'], selection['projects'][context['project']]['url'])
                ensure_revision(repo, context['commit'])
                data = git(repo, 'show', f"{context['commit']}:{metadata['path']}")
                if digest(data) != metadata['sha256']:
                    raise SystemExit('Metadata hash mismatch.')
                save_blob(target, data)
            if not target.exists() or digest(target.read_bytes()) != metadata['sha256']:
                raise SystemExit(f'Missing or modified metadata: {target}')
    print(f"verified {len(result['contexts'])} contexts")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['freeze', 'fetch', 'verify'])
    run(parser.parse_args().mode)
