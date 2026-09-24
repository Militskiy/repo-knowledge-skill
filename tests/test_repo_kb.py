"""Offline correctness, safety, and retrieval tests; never execute indexed code."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/repo-knowledge/scripts/repo_kb.py'
spec = importlib.util.spec_from_file_location('repo_kb', SCRIPT)
kb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kb)


class RepoKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.out = Path(self.temp.name) / 'index'
        self.write('go.mod', 'module example.org/panel\n\ngo 1.22\n')
        self.write('service/traffic.go', '''package service
// ResetClientTraffic clears usage counters for one client.
func ResetClientTraffic(email string) error {
    return nil
}

// ReadQuota gets the allocated client bytes.
func ReadQuota(email string) int {
    return 10
}
''')
        self.write('controller/traffic.go', '''package controller
import "example.org/panel/service"
func ResetHandler() error {
    return service.ResetClientTraffic("sample")
}
''')
        self.write('service/traffic_test.go', '''package service
func TestReset(t *testing.T) {
    ResetClientTraffic("sample")
}
''')
        self.write('README.md', '# Panel\n\n[Traffic](service/traffic.go)\n')

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def build(self):
        return kb.build(self.root, self.out, filesystem=True)

    def db(self):
        folder, _ = kb.current(self.out)
        return kb.connect(folder / 'index.sqlite3', True)

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = kb.main(['--repo', str(self.root), '--output', str(self.out), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_build_and_unchanged(self):
        result = self.build()
        self.assertEqual(result['files'], 5)
        self.assertGreater(result['edges'], result['chunks'])
        again = self.build()
        self.assertEqual(again['state'], 'unchanged')
        self.assertEqual(again['reindexed'], 0)

    def test_identifier_search(self):
        self.build()
        code, text, _ = self.cli('query', 'reset client traffic')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)['results'][0]['title'], 'ResetClientTraffic')

    def test_exact_identifier_search(self):
        self.build()
        _, text, _ = self.cli('query', 'ReadQuota')
        self.assertEqual(json.loads(text)['results'][0]['title'], 'ReadQuota')

    def test_source_ranges_are_exact(self):
        self.build()
        with contextlib.closing(self.db()) as db:
            row = kb.search(db, 'ReadQuota')[0]
        code, text, _ = self.cli('show', row['id'])
        self.assertEqual(code, 0)
        payload = json.loads(text)
        lines = (self.root / row['path']).read_text().splitlines()
        for result in payload['results']:
            self.assertEqual(result['text'], lines[result['line'] - 1])
        self.assertEqual(payload['sha256'], kb.digest((self.root / row['path']).read_bytes()))

    def test_stale_sources_fail_closed(self):
        self.build()
        self.write('service/traffic.go', 'package service\nfunc NewThing() {}\n')
        code, text, error = self.cli('query', 'traffic')
        self.assertEqual(code, 2)
        self.assertEqual(text, '')
        self.assertIn('stale index', error)
        self.assertEqual(self.cli('status')[0], 3)

    def test_same_mtime_and_size_detected(self):
        self.build()
        path = self.root / 'service/traffic.go'
        stat = path.stat()
        path.write_text(path.read_text().replace('return 10', 'return 20'))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertFalse(kb.freshness(self.root, self.out)[2]['fresh'])

    def test_incremental_add_delete_update(self):
        self.build()
        (self.root / 'controller/traffic.go').unlink()
        self.write('new.py', 'def AddedFunction():\n    return 1\n')
        self.write('service/traffic.go', 'package service\nfunc ChangedFunction() {}\n')
        result = self.build()
        self.assertEqual(result['removed'], 1)
        self.assertEqual(result['reindexed'], 2)
        with contextlib.closing(self.db()) as db:
            self.assertFalse(db.execute("SELECT 1 FROM chunks WHERE title='ResetHandler'").fetchone())
            ids = {r[0] for r in db.execute('SELECT id FROM chunks')}
            ids |= {kb.ident('f', r[0]) for r in db.execute('SELECT path FROM files')}
            for row in db.execute('SELECT src,dst FROM edges'):
                self.assertTrue(set(row).issubset(ids))

    def test_incremental_equals_clean_index(self):
        self.build()
        self.write('more.py', 'def ExtraSymbol():\n    return 1\n')
        self.build()
        other = self.out.parent / 'clean'
        kb.build(self.root, other, filesystem=True)
        folder, _ = kb.current(other)
        with contextlib.closing(self.db()) as a, contextlib.closing(kb.connect(folder / 'index.sqlite3', True)) as b:
            for table in ('files', 'chunks', 'search', 'edges'):
                self.assertEqual(sorted(map(tuple, a.execute('SELECT * FROM ' + table))),
                                 sorted(map(tuple, b.execute('SELECT * FROM ' + table))))

    def test_source_revert_reuses_generation(self):
        first = self.build()['fingerprint']
        source = (self.root / 'README.md').read_text()
        self.write('README.md', source + '\nChanged.\n')
        self.build()
        self.write('README.md', source)
        self.assertEqual(self.build()['fingerprint'], first)
        self.assertTrue(kb.freshness(self.root, self.out)[2]['fresh'])

    def test_graph_import_mentions_tests_and_docs(self):
        self.build()
        with contextlib.closing(self.db()) as db:
            kinds = {r[0] for r in db.execute('SELECT kind FROM edges')}
        self.assertTrue({'imports', 'mentions', 'tests', 'documents', 'contains'} <= kinds)
        code, output, _ = self.cli('neighbors', kb.ident('f', 'service/traffic.go'))
        self.assertEqual(code, 0)
        self.assertTrue(any(r['kind'] == 'imports' and r['direction'] == 'in'
                            for r in json.loads(output)['results']))

    def test_ambiguous_symbols_do_not_make_reference_edges(self):
        self.write('a.py', 'def DuplicateName():\n    pass\n')
        self.write('b.py', 'def DuplicateName():\n    pass\n')
        self.write('c.py', 'DuplicateName()\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            self.assertFalse(db.execute("SELECT 1 FROM edges WHERE evidence='unique lexical symbol: DuplicateName'").fetchone())

    def test_markdown_links_resolve(self):
        self.write('odd [name] ü.md', '# Unicode title\n')
        self.build()
        folder, _ = kb.current(self.out)
        for doc in folder.rglob('*.md'):
            for target in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
                self.assertTrue((doc.parent / unquote(target)).resolve().exists(), (doc, target))

    def test_secret_binary_vendor_and_large_files_skipped(self):
        self.write('.env', 'PASSWORD=secret\n')
        self.write('private.pem', 'private-key-placeholder')
        self.write('vendor/tool.py', 'def Unwanted(): pass\n')
        self.write('secret.txt', '-----BEGIN PRIVATE KEY-----\nprivate\n')
        self.write('large.txt', 'x' * (kb.MAX_FILE + 1))
        self.write('binary.txt', '\0hidden\n')
        (self.root / 'bad.txt').write_bytes(b'\xff\xfe')
        result = self.build()
        self.assertEqual(result['files'], 5)
        self.assertEqual(result['skipped']['secret-pattern'], 1)
        self.assertEqual(result['skipped']['oversize'], 1)
        self.assertEqual(result['skipped']['non-utf8'], 1)

    def test_symlink_files_and_directories_not_followed(self):
        outside = self.out.parent / 'outside.py'
        outside.write_text('EXTERNAL_SECRET = 1\n')
        (self.root / 'link.py').symlink_to(outside)
        (self.root / 'linked-dir').symlink_to(self.out.parent, target_is_directory=True)
        self.assertEqual(self.build()['files'], 5)

    def test_unsafe_paths_rejected(self):
        for path in ('../outside.py', '/etc/passwd', 'a/../../b', 'a\\b'):
            with self.assertRaises(kb.KBError):
                kb.safe_path(self.root, path)

    def test_output_safety(self):
        self.out.mkdir()
        (self.out / 'user-file.txt').write_text('keep')
        with self.assertRaises(kb.KBError):
            self.build()
        self.assertEqual((self.out / 'user-file.txt').read_text(), 'keep')
        self.assertEqual(kb.main(['--repo', str(self.root), '--output', str(self.root), 'build', '--filesystem']), 2)

    def test_output_symlink_refused(self):
        self.out.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.cli('build', '--filesystem')[0], 2)

    def test_lock_does_not_get_removed_by_other_builder(self):
        self.build()
        lock = self.out / 'BUILD.lock'
        lock.write_text('occupied')
        with self.assertRaises(kb.KBError):
            self.build()
        self.assertTrue(lock.exists())

    def test_config_aliases_and_freshness(self):
        self.build()
        self.write('.repo-knowledge.json', json.dumps({'aliases': {'allowance': ['ReadQuota']}}))
        self.assertFalse(kb.freshness(self.root, self.out)[2]['fresh'])
        self.build()
        _, text, _ = self.cli('query', 'allowance')
        self.assertEqual(json.loads(text)['results'][0]['title'], 'ReadQuota')

    def test_invalid_config(self):
        for cfg in ({'execute': 'bad'}, {'exclude': 'not a list'}, {'aliases': {'a': 'b'}}):
            self.write('.repo-knowledge.json', json.dumps(cfg))
            with self.assertRaises(kb.KBError):
                self.build()

    def test_fts_query_syntax_is_not_executed(self):
        self.build()
        for query in ('" OR * NOT ((( ReadQuota', '!!!', "'; DROP TABLE files; --", 'where is the'):
            self.assertEqual(self.cli('query', query)[0], 0)
        with contextlib.closing(self.db()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM files').fetchone()[0], 5)

    def test_complete_utf8_json_budget(self):
        items = [{'snippet': '你好🙂' * 70, 'id': str(i)} for i in range(30)]
        for budget in (128, 256, 512, 1200):
            text = kb.pack({'snapshot': 'abc'}, items, budget)
            self.assertLessEqual(len(text.encode('utf-8')), budget * 4)
            payload = json.loads(text)
            self.assertEqual(len(payload['results']) + payload['omitted'], len(items))

    def test_query_budget_includes_metadata(self):
        self.build()
        _, text, _ = self.cli('query', 'client', '--budget', '128')
        self.assertLessEqual(len(text.encode()), 512)
        json.loads(text)

    def test_chunk_boundaries_and_stable_ids(self):
        body = '\n'.join(['package a', 'func LargeFunction() {'] + ['// data'] * 500 + ['}'])
        first = kb.chunks('a.go', body)
        second = kb.chunks('a.go', '// inserted\n' + body)
        self.assertTrue(all(c['end'] - c['start'] + 1 <= kb.CHUNK_LINES for c in first))
        self.assertEqual([c['id'] for c in first if c['title'] == 'LargeFunction'],
                         [c['id'] for c in second if c['title'] == 'LargeFunction'])
        covered = [n for c in first for n in range(c['start'], c['end'] + 1)]
        self.assertEqual(covered, list(range(1, len(body.splitlines()) + 1)))

    def test_repository_code_is_never_executed(self):
        marker = self.out.parent / 'executed'
        self.write('script.py', f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        self.write('install.sh', f'touch "{marker}"\n')
        self.build()
        self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which('git'), 'Git required')
    def test_git_tracked_and_ignored_untracked(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.write('.gitignore', 'ignored.py\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        self.write('ignored.py', 'ignored\n')
        self.write('untracked.py', 'untracked\n')
        first = kb.build(self.root, self.out)
        self.assertEqual(first['files'], 5)
        second = kb.build(self.root, self.out, untracked=True)
        self.assertEqual(second['files'], 6)
        with contextlib.closing(self.db()) as db:
            self.assertFalse(db.execute("SELECT 1 FROM files WHERE path='ignored.py'").fetchone())

    def test_index_in_repo_is_not_self_indexed(self):
        self.out = self.root / '.repo-knowledge'
        self.build()
        self.assertEqual(self.build()['state'], 'unchanged')

    def test_unknown_node_errors(self):
        self.build()
        self.assertEqual(self.cli('show', 'c-unknown')[0], 2)
        self.assertEqual(self.cli('neighbors', 'f-unknown')[0], 2)

    def test_new_file_detected_in_filesystem_mode(self):
        self.build()
        self.write('new.go', 'package new\n')
        self.assertEqual(kb.freshness(self.root, self.out)[2]['added'], ['new.go'])

    def test_empty_repo_and_search(self):
        for p in list(self.root.iterdir()):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        self.assertEqual(self.build()['files'], 0)
        self.assertEqual(json.loads(self.cli('query', 'anything')[1])['results'], [])


    def test_show_pagination_preserves_every_source_line(self):
        self.write('long.py', 'def LongRoutine():\n' + '    value = "' + 'x' * 70 + '"\n' +
                   ''.join(f'    value_{i} = {i}\n' for i in range(55)))
        self.build()
        with contextlib.closing(self.db()) as db:
            row = kb.search(db, 'LongRoutine')[0]
        offset, collected = 0, []
        for _ in range(20):
            code, text, _ = self.cli('show', row['id'], '--budget', '256', '--offset', str(offset))
            self.assertEqual(code, 0)
            payload = json.loads(text)
            collected.extend(payload['results'])
            if payload['next_offset'] is None:
                break
            self.assertGreater(payload['next_offset'], offset)
            offset = payload['next_offset']
        self.assertEqual([r['line'] for r in collected], list(range(row['start'], row['end'] + 1)))

    def test_query_offset_matches_ranked_slice(self):
        self.build()
        whole = json.loads(self.cli('query', 'client', '--limit', '5')[1])['results']
        page = json.loads(self.cli('query', 'client', '--limit', '2', '--offset', '1')[1])['results']
        self.assertEqual(page, whole[1:3])

    def test_python_and_javascript_import_links(self):
        self.write('pkg/helpers.py', 'def Helper(): pass\n')
        self.write('pkg/main.py', 'from .helpers import Helper\n')
        self.write('entry.py', 'import pkg.helpers\n')
        self.write('front/a.ts', 'export const Example = () => 1;\n')
        self.write('front/b.ts', 'import { Example } from "./a";\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            edges = {tuple(r) for r in db.execute("SELECT src,dst FROM edges WHERE kind='imports'")}
        for source, target in [('pkg/main.py', 'pkg/helpers.py'), ('entry.py', 'pkg/helpers.py'),
                               ('front/b.ts', 'front/a.ts')]:
            self.assertIn((kb.ident('f', source), kb.ident('f', target)), edges)

    def test_leading_comments_belong_to_declaration(self):
        body = 'package a\n\n// Unique description.\nfunc Example() {}\n'
        row = next(c for c in kb.chunks('a.go', body) if c['title'] == 'Example')
        self.assertEqual(row['start'], 3)
        self.assertIn('Unique description', row['body'])

    def test_failed_build_preserves_published_generation(self):
        self.build()
        before = (self.out / 'CURRENT').read_text()
        self.write('new.py', 'def NewDeclaration(): pass\n')
        with mock.patch.object(kb, 'export_maps', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual((self.out / 'CURRENT').read_text(), before)
        self.assertFalse((self.out / 'BUILD.lock').exists())
        self.assertFalse(list((self.out / 'generations').glob('.building-*')))

    def test_invalid_pointer_and_symlinked_database_rejected(self):
        self.build()
        pointer = self.out / 'CURRENT'
        before = pointer.read_text()
        pointer.write_text('../../outside')
        self.assertEqual(self.cli('query', 'client')[0], 2)
        pointer.write_text(before)
        folder, _ = kb.current(self.out)
        (folder / 'index.sqlite3').unlink()
        (folder / 'index.sqlite3').symlink_to(self.root / 'README.md')
        self.assertEqual(self.cli('query', 'client')[0], 2)

    def test_scope_overflow_fails_explicitly(self):
        with mock.patch.object(kb, 'MAX_FILES', 2):
            with self.assertRaisesRegex(kb.KBError, 'limit exceeded'):
                self.build()

    def test_portable_skill_frontmatter_and_copied_cli(self):
        skill = SCRIPT.parents[1]
        frontmatter = (skill / 'SKILL.md').read_text().split('---', 2)[1]
        self.assertIn('name: repo-knowledge', frontmatter)
        self.assertRegex(frontmatter, r'description: .+')
        self.assertLess(len((skill / 'SKILL.md').read_bytes()), 10000)
        for layout in ('.agents/skills', '.config/opencode/skills'):
            install = self.out.parent / layout / 'repo-knowledge'
            shutil.copytree(skill, install, ignore=shutil.ignore_patterns('__pycache__'))
            run = subprocess.run([__import__('sys').executable, str(install / 'scripts/repo_kb.py'),
                                  '--repo', str(self.root), '--output', str(self.out),
                                  'build', '--filesystem'], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['files'], 5)


if __name__ == '__main__':
    unittest.main()
