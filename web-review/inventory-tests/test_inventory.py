import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from change_inventory import parse_raw, parse_numstat, inventory
from corpus import git


class InventoryTests(unittest.TestCase):
    def test_nul_paths_and_binary_counts_do_not_lose_files(self):
        filename = '한글\t파일\nname.tsx'
        raw = b':100644 100644 ' + b'a' * 40 + b' ' + b'b' * 40 + b' M\0' + filename.encode() + b'\0'
        self.assertEqual(parse_raw(raw)[0]['path'], filename)
        self.assertEqual(parse_numstat(b'2\t1\t' + filename.encode() + b'\0')[filename]['addedLines'], 2)
        self.assertEqual(parse_numstat(b'-\t-\tbinary.dat\0')['binary.dat'], {
            'addedLines': None, 'removedLines': None, 'binary': True,
        })
        for malformed in [raw[:-1], raw + raw, raw.replace(b' M\0', b' R100\0')]:
            with self.assertRaises(ValueError):
                parse_raw(malformed)
        for malformed in [b'1\t2\tpath', b'-\t1\tpath\0', b'1\t2\tpath\0' * 2]:
            with self.assertRaises(ValueError):
                parse_numstat(malformed)

    def test_original_git_diff_retains_unselected_added_deleted_and_binary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, 'init', '-q')
            (repo / 'selected.ts').write_text('export const a = 1;\n', encoding='utf-8')
            (repo / 'old.txt').write_text('same rename content\n', encoding='utf-8')
            git(repo, 'add', '.')
            git(repo, '-c', 'user.name=Geul test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'before')
            before = git(repo, 'rev-parse', 'HEAD').decode().strip()
            (repo / 'selected.ts').write_text('export const a = 2;\n', encoding='utf-8')
            (repo / 'old.txt').rename(repo / 'new.txt')
            (repo / 'unknown.css').write_text('.button { display: none; }\n', encoding='utf-8')
            (repo / 'binary.dat').write_bytes(b'\x00\x01\x02')
            git(repo, 'add', '.')
            git(repo, '-c', 'user.name=Geul test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'after')
            after = git(repo, 'rev-parse', 'HEAD').decode().strip()
            result = inventory(repo, before, after, ['selected.ts'])
            rows = {row['path']: row for row in result['changedFiles']}
            self.assertEqual(set(rows), {'selected.ts', 'old.txt', 'new.txt', 'unknown.css', 'binary.dat'})
            self.assertEqual(rows['old.txt']['status'], 'D')
            self.assertEqual(rows['new.txt']['status'], 'A')
            self.assertTrue(rows['binary.dat']['binary'])
            self.assertTrue(rows['selected.ts']['selectedInCorpus'])
            self.assertFalse(rows['unknown.css']['selectedInCorpus'])
            self.assertIsNone(rows['old.txt']['afterBlob'])
            self.assertIsNone(rows['new.txt']['beforeBlob'])


if __name__ == '__main__':
    unittest.main()
