"""Repository-neutral invariants; no benchmark vocabulary or pinned paths."""
import contextlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock

import test_repo_kb as fixture

kb = fixture.kb


class EvidenceTests(unittest.TestCase):
    setUp = fixture.RepoKnowledgeTests.setUp
    tearDown = fixture.RepoKnowledgeTests.tearDown
    write = fixture.RepoKnowledgeTests.write
    build = fixture.RepoKnowledgeTests.build
    db = fixture.RepoKnowledgeTests.db
    cli = fixture.RepoKnowledgeTests.cli

    def test_discovery_accepts_text_without_language_or_layout_allowlists(self):
        names = ['build/compile.py', 'dist/package.rs', 'target/machine.nim',
                 'lib/render.ejs', 'scripts/task', '.editorconfig', 'a.cs', 'b.ex',
                 'c.lua', 'data.R', 'go.sum', 'Cargo.lock', '.env.example', '.environment']
        for name in names:
            self.write(name, 'readable project artifact\n')
        files, skipped = kb.discover(self.root, self.out, kb.settings(self.root, True, False))
        self.assertTrue(set(names) <= set(files))
        self.assertFalse(skipped)

    def test_audit_explains_files_and_pruned_directories(self):
        self.write('.env.local', 'PASSWORD=hidden\n')
        self.write('data.bin', '\0not text')
        self.write('vendor/dependency.py', 'print(1)\n')
        code, text, err = self.cli('scope', '--filesystem', '--budget', '3000')
        self.assertEqual(code, 0, err)
        payload = json.loads(text)
        reasons = {r['path']: r['reason'] for r in payload['results']}
        self.assertEqual(reasons['.env.local'], 'sensitive-path')
        self.assertEqual(reasons['data.bin'], 'binary-or-minified')
        self.assertEqual(reasons['vendor/'], 'untracked-dependency-directory')
        self.assertEqual(payload['coverage']['pruned_directories'], 1)
        self.assertEqual(payload['coverage']['included_files'], 5)

    def test_explicit_scope_cannot_override_safety_or_exclude(self):
        self.write('vendor/helper.ml', 'let answer = 7\n')
        self.write('vendor/.env', 'secret\n')
        self.write('vendor/key.txt', '-----BEGIN PRIVATE KEY-----\n')
        self.write('vendor/omit.ml', 'let answer = 3\n')
        self.write('.repo-knowledge.json', json.dumps({'include': ['vendor/*'], 'exclude': ['*/omit.ml']}))
        files, skipped = kb.discover(self.root, self.out, kb.settings(self.root, True, False))
        self.assertEqual(set(files), {'vendor/helper.ml'})
        self.assertEqual(skipped['secret-pattern'], 1)
        self.assertEqual(skipped['sensitive-path'], 1)
        self.assertEqual(skipped['configured-exclude'], 1)

    def test_scope_configuration_changes_require_rebuild(self):
        self.build()
        self.write('.repo-knowledge.json', json.dumps({'include': ['service/*']}))
        self.assertEqual(self.cli('query', 'client')[0], 2)
        self.build()
        self.assertEqual(self.cli('query', 'client')[0], 0)

    @unittest.skipUnless(shutil.which('git'), 'Git required')
    def test_tracked_dependency_source_is_not_silently_pruned(self):
        self.write('vendor/original.ex', 'defmodule Original do\nend\n')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True, capture_output=True)
        files, _ = kb.discover(self.root, self.out, kb.settings(self.root, False, False))
        self.assertIn('vendor/original.ex', files)

    def test_ast_keeps_nested_callbacks_and_assertions_together(self):
        source = '@decorate(\n    value=1\n)\ndef test_wrapped():\n    """class Imaginary is prose."""\n    def callback():\n        return 7\n    assert callback() == 7\n\nAFTER = 2\n'
        rows = kb.chunks('nested.py', source)
        row = next(r for r in rows if r['symbol'] == 'test_wrapped')
        self.assertEqual((row['start'], row['end']), (1, 8))
        self.assertIn('assert callback()', row['body'])
        self.assertNotIn('AFTER', row['body'])
        self.assertEqual(row['method'], 'python-ast')
        self.assertNotIn('Imaginary', [r['title'] for r in rows])

    def test_ast_ranges_cover_class_members_and_gaps_once(self):
        source = 'class Widget:\n    """description"""\n    field = 1\n    # leading note\n    def run(self):\n        return self.field\n\n    constant = 2\n\ndef outside():\n    return 3\n'
        rows = kb.chunks('thing.py', source)
        covered = [n for r in rows for n in range(r['start'], r['end']+1)]
        self.assertEqual(covered, list(range(1, len(source.splitlines())+1)))
        self.assertIn('Widget.run', [r['title'] for r in rows])
        self.assertTrue(all(r['body'] == '\n'.join(source.splitlines()[r['start']-1:r['end']]) for r in rows))

    def test_parse_failure_and_unknown_language_keep_source(self):
        for path, source in [('future.py', 'def broken(\n    arbitrary syntax\n'),
                             ('source.xyz', '\n'.join('statement ' + str(i) for i in range(170)))]:
            rows = kb.chunks(path, source)
            self.assertEqual('\n'.join(r['body'] for r in rows), source.rstrip('\n'))
            self.assertTrue(all(r['end']-r['start'] < kb.CHUNK_LINES for r in rows))

    def test_assignment_c_definition_and_rst_sections(self):
        js = kb.chunks('api.cjs', 'obj.action = function(value) {\n return value;\n};\n')
        self.assertEqual(js[0]['symbol'], 'obj.action')
        c = kb.chunks('unit.c', 'static int evaluate(\n    int value) {\n return value;\n}\n')
        self.assertEqual(c[0]['symbol'], 'evaluate')
        rst = kb.chunks('guide.rst', 'Title\n=====\n\nDetails\n-------\ntext\n')
        self.assertEqual([r['title'] for r in rst], ['Title', 'Details'])

    def test_markdown_fences_are_not_headings(self):
        rows = kb.chunks('notes.md', '# Real\n```sh\n# not a heading\n```\n## Next\ntext\n')
        self.assertEqual([r['title'] for r in rows], ['Real', 'Next'])

    def test_intent_distinguishes_definition_reference_and_test(self):
        self.write('api.py', 'def ProcessBatch(value):\n    return value + 1\n')
        self.write('consumer.py', 'def consume():\n    return ProcessBatch(8)\n')
        self.write('tests/test_api.py', 'def test_value():\n    assert ProcessBatch(8) == 9\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            self.assertEqual(kb.search(db, 'ProcessBatch definition')[0]['path'], 'api.py')
            self.assertEqual(kb.search(db, 'tests ProcessBatch')[0]['path'], 'tests/test_api.py')
            self.assertNotEqual(kb.search(db, 'Who calls ProcessBatch?')[0]['path'], 'api.py')

    def test_unknown_identifier_does_not_claim_component_match(self):
        self.write('words.md', '# Glacier\nA ledger and reconcile operation.\n')
        self.build()
        payload = json.loads(self.cli('query', 'GlacierLedgerReconcile')[1])
        self.assertEqual(payload['results'], [])
        self.assertEqual(payload['assessment'], 'no-match')
        self.assertIn('absence', payload['limitations'])

    def test_partial_natural_question_is_low_support(self):
        self.build()
        response = json.loads(self.cli('query', 'traffic quasar orbital fusion membrane')[1])
        self.assertEqual(response['assessment'], 'low-support')
        self.assertTrue(response['retrieval']['missing_terms'])

    def test_exact_duplicate_excerpts_do_not_fill_result_set(self):
        self.write('a.py', 'def DistinctNeedle():\n    return 7\n')
        self.write('b.py', 'def DistinctNeedle():\n    return 7\n')
        self.write('c.py', 'def use():\n    return DistinctNeedle() + 1\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            info = {}
            rows = kb.search(db, 'DistinctNeedle', limit=10, diagnostics=info)
        self.assertEqual(sum(r['symbol'] == 'DistinctNeedle' for r in rows), 1)
        self.assertEqual(info['deduplicated'], 1)
        self.assertIn('c.py', [r['path'] for r in rows])

    def test_file_show_and_context_preserve_source(self):
        self.build()
        code, text, err = self.cli('show', kb.ident('f', 'service/traffic.go'))
        self.assertEqual(code, 0, err)
        self.assertEqual('\n'.join(x['text'] for x in json.loads(text)['results']),
                         (self.root/'service/traffic.go').read_text().rstrip('\n'))
        with contextlib.closing(self.db()) as db:
            chunk = kb.search(db, 'ReadQuota')[0]
        payload = json.loads(self.cli('show', chunk['id'], '--context', '2')[1])
        self.assertEqual(payload['start'], chunk['start']-2)

    def test_navigation_labels_call_syntax_and_filters(self):
        self.write('unique.py', 'def UniqueThing():\n    return 1\n')
        self.write('consumer.py', 'def consumer():\n    return UniqueThing()\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            row = kb.search(db, 'UniqueThing definition')[0]
        payload = json.loads(self.cli('neighbors', row['id'], '--kind', 'call-syntax', '--direction', 'in')[1])
        self.assertTrue(payload['results'])
        self.assertTrue(all(r['kind'] == 'call-syntax' and r['inferred'] for r in payload['results']))
        self.assertIn('binding unresolved', payload['results'][0]['evidence'])

    def test_collection_contains_multiple_verified_artifacts_with_total_budget(self):
        self.build()
        for budget in (400, 900, 1800):
            code, text, err = self.cli('collect', 'reset client traffic', '--budget', str(budget))
            self.assertEqual(code, 0, err)
            self.assertLessEqual(len(text.encode()), budget * 4)
            payload = json.loads(text)
            for row in payload['results']:
                raw = (self.root / row['path']).read_bytes()
                self.assertEqual(row['sha256'], kb.digest(raw))
                self.assertEqual(row['text'], '\n'.join(raw.decode().splitlines()[row['start']-1:row['end']]))
        self.assertGreaterEqual(len({r['path'] for r in payload['results']}), 2)
        self.assertIn(payload['stop_reason'], {'budget-or-limit', 'candidates-exhausted'})

    def test_collection_pagination_and_staleness(self):
        self.build()
        first = json.loads(self.cli('collect', 'client', '--limit', '1')[1])
        self.assertIsNotNone(first['next_offset'])
        second = json.loads(self.cli('collect', 'client', '--limit', '1', '--offset', str(first['next_offset']))[1])
        self.assertNotEqual(first['results'][0]['id'], second['results'][0]['id'])
        self.write('service/traffic.go', 'new bytes\n')
        self.assertEqual(self.cli('collect', 'client')[0], 2)

    def test_source_identity_is_distinct_from_configuration_and_checkout(self):
        self.build()
        _, initial = kb.current(self.out)
        self.write('.repo-knowledge.json', json.dumps({'aliases': {'allowance': ['quota']}}))
        self.build()
        _, changed = kb.current(self.out)
        self.assertEqual(initial['source_id'], changed['source_id'])
        self.assertNotEqual(initial['fingerprint'], changed['fingerprint'])
        self.assertEqual(changed['build_version_control'], {'kind': 'filesystem', 'head': None})

    @unittest.skipUnless(shutil.which('git'), 'Git required')
    def test_head_change_does_not_misrepresent_source_freshness(self):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), '-c', 'user.name=Test',
                                           '-c', 'user.email=test@example.invalid', *args], stderr=subprocess.STDOUT)
        git('init', '-q')
        git('add', '.')
        git('commit', '-qm', 'first')
        kb.build(self.root, self.out)
        git('commit', '--allow-empty', '-qm', 'metadata only')
        report = kb.freshness(self.root, self.out)[2]
        self.assertTrue(report['fresh'])
        self.assertEqual(report['source_id'], report['indexed_source_id'])
        self.assertNotEqual(report['build_version_control']['head'], report['current_version_control']['head'])
        self.assertEqual(kb.build(self.root, self.out)['state'], 'unchanged')

    def test_current_exclusion_changes_are_inspectable_without_staling_source(self):
        self.build()
        self.write('.env.local', 'private\n')
        self.assertTrue(kb.freshness(self.root, self.out)[2]['fresh'])
        _, meta = kb.ready(self.root, self.out)
        self.assertEqual(meta['skipped']['sensitive-path'], 1)

    def test_direct_build_refuses_source_as_output(self):
        with self.assertRaises(kb.KBError):
            kb.build(self.root, self.root, filesystem=True)

    def test_scope_filters_do_not_change_global_coverage_summary(self):
        self.build()
        data = json.loads(self.cli('scope', '--path', 'service/*')[1])
        self.assertEqual(data['coverage']['included_files'], 5)
        self.assertTrue(all(r['path'].startswith('service/') for r in data['results']))

    def test_multiple_call_sites_share_one_edge_without_losing_evidence(self):
        self.write('definition.py', 'def UniqueTarget():\n    return 1\n')
        self.write('caller.py', 'def caller():\n    UniqueTarget()\n    UniqueTarget()\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            edges = list(db.execute("SELECT * FROM edges WHERE kind='call-syntax'"))
        self.assertEqual(len(edges), 1)
        self.assertIn('L2', edges[0]['evidence'])
        self.assertIn('L3', edges[0]['evidence'])

    def test_path_scope_applies_before_candidate_limit(self):
        self.write('crowded.py', '\n'.join(f'def Needle{i}():\n    return "needle"' for i in range(410)))
        self.write('wanted.rs', 'fn desired() { /* needle */ }\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            rows = kb.search(db, 'needle', path_glob='wanted.*')
        self.assertEqual([r['path'] for r in rows], ['wanted.rs'])

    def test_git_special_entries_are_explained_without_following_them(self):
        self.write('link.py', 'outside.py')  # Windows may materialize a Git symlink as text.
        entries = '120000 ' + 'a'*40 + ' 0\tlink.py\0' + '160000 ' + 'b'*40 + ' 0\tcomponent\0'
        audit = []
        with mock.patch.object(kb, 'git', return_value=entries):
            files, skipped = kb.discover(self.root, self.out, kb.settings(self.root, False, False), audit)
        self.assertEqual(files, {})
        self.assertEqual(skipped, {'git-symlink': 1, 'gitlink-not-expanded': 1})

    def test_nondefault_owned_outputs_are_not_indexed(self):
        self.write('other-index/.owned-by-repo-knowledge', '2')
        self.write('other-index/navigation.md', 'generated evidence\n')
        files, skipped = kb.discover(self.root, self.out, kb.settings(self.root, True, False))
        self.assertNotIn('other-index/navigation.md', files)
        self.assertEqual(skipped['tool-output'], 1)

    def test_collection_budget_bounds_tiny_and_large_lines(self):
        self.write('wide.py', 'def WideLine():\n    value = "' + 'x' * 3900 + '"\n    return value\n')
        self.build()
        for budget in (128, 256, 400, 1200):
            code, text, err = self.cli('collect', 'WideLine', '--budget', str(budget))
            if code == 2:
                self.assertIn('budget too small for response metadata', err)
            else:
                self.assertLessEqual(len(text.encode()), 4 * budget)
                json.loads(text)

    def test_stable_evidence_anchor_keeps_lines_when_context_grows(self):
        source = 'def calculate():\n    """calculate the abort condition"""\n' + '    value = 0\n' * 20 + '    if abort:\n        return None\n'
        row = kb.chunks('behavior.py', source)[0]
        previous = set()
        for length in (1, 3, 6, 10, 16, 24, 64):
            lo, hi = kb.evidence_window(row, 'How does calculate abort?', length)
            points = set(range(lo, hi + 1))
            self.assertTrue(previous <= points)
            self.assertIn(23, points)
            previous = points

    def test_intent_does_not_confuse_subject_with_requested_artifact(self):
        self.assertEqual(kb.query_plan('Which command configures the test support environment?')['intent'], 'any')
        self.assertEqual(kb.query_plan('Which tests verify the operation?')['intent'], 'tests')
        self.assertEqual(kb.query_plan('How is the operation implemented and tested?')['intent'], 'mixed')

    def test_implementation_prefers_body_to_stub_when_syntax_is_reliable(self):
        self.write('a.pyi', 'def PerformWork(): ...\n')
        self.write('b.py', 'def PerformWork():\n    return 42\n')
        self.build()
        with contextlib.closing(self.db()) as db:
            rows = kb.search(db, 'PerformWork implementation')
        self.assertEqual(rows[0]['path'], 'b.py')
        self.assertEqual(next(r['kind'] for r in rows if r['path'] == 'a.pyi'), 'declaration')


if __name__ == '__main__':
    unittest.main()
