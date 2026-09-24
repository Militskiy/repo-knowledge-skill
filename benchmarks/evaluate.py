#!/usr/bin/env python3
"""Evaluate an existing pinned checkout or verified subset; never fetch or run it."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import sqlite3
import tempfile
import time
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/repo-knowledge/scripts/repo_kb.py'
spec = importlib.util.spec_from_file_location('repo_kb', SCRIPT)
kb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kb)


def blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def invoke(repo: Path, out: Path, command: str, **kwargs) -> tuple[str, dict]:
    args = argparse.Namespace(repo=str(repo), output=str(out), command=command,
                              budget=900, offset=0, limit=5)
    for key, value in kwargs.items():
        setattr(args, key, value)
    text, code = kb.run(args)
    if code != 0:
        raise RuntimeError('retrieval failed: ' + text)
    if len(text.encode()) > args.budget * 4:
        raise RuntimeError('response exceeded budget')
    return text, json.loads(text)


def evaluate(repo: Path, scope: str) -> dict:
    fixture = json.loads((ROOT / 'benchmarks/3x-ui.json').read_text())
    for name, expected in fixture['files'].items():
        path = kb.safe_path(repo, name)
        if not path.is_file() or blob_sha(path) != expected:
            raise ValueError('pinned blob mismatch: ' + name)
    if scope == 'full':
        if kb.git(repo, 'rev-parse', 'HEAD').strip() != fixture['commit']:
            raise ValueError('checkout is not the pinned revision')
        if kb.git(repo, 'status', '--porcelain').strip():
            raise ValueError('full checkout must be clean before evaluation')
    else:
        names = {p.relative_to(repo).as_posix() for p in repo.rglob('*') if p.is_file()}
        if names != set(fixture['files']):
            raise ValueError('subset must contain exactly the ten fixture files')

    with tempfile.TemporaryDirectory(prefix='repo-kb-evaluation-') as temporary:
        out = Path(temporary) / 'index'
        start = time.perf_counter()
        built = kb.build(repo, out, filesystem=scope == 'subset')
        elapsed = time.perf_counter() - start
        again = kb.build(repo, out, filesystem=scope == 'subset')
        if again['reindexed'] != 0 or again['state'] != 'unchanged':
            raise RuntimeError('no-op build failed')
        folder, meta = kb.current(out)
        with closing(kb.connect(folder / 'index.sqlite3', True)) as db, closing(sqlite3.connect(':memory:')) as plain:
            chunks = {r['id']: dict(r) for r in db.execute('SELECT * FROM chunks')}
            nodes = set(chunks) | {kb.ident('f', r[0]) for r in db.execute('SELECT path FROM files')}
            edges = list(db.execute('SELECT * FROM edges'))
            if any(e['src'] not in nodes or e['dst'] not in nodes for e in edges):
                raise RuntimeError('dangling graph edge')
            # Raw body-only FTS5 baseline: same source chunks, no identifier
            # expansion, path/title weighting, coverage reranking or diversity.
            plain.execute("CREATE VIRTUAL TABLE baseline USING fts5(id UNINDEXED, body, tokenize='porter unicode61')")
            plain.executemany('INSERT INTO baseline VALUES (?,?)',
                              [(c['id'], c['body']) for c in chunks.values()])
            rows = []
            for case in fixture['cases']:
                gold = {c['id'] for c in chunks.values()
                        if c['path'] == case['path'] and c['title'] == case['title']}
                if not gold:
                    raise ValueError('gold declaration not found: ' + case['title'])
                query_text, response = invoke(repo, out, 'query', query=case['query'])
                terms = sorted(set(re.findall(r'[^\W_]+', case['query'].lower())) - kb.STOP)
                match = ' OR '.join('"' + t + '"' for t in terms)
                matches = plain.execute('SELECT id FROM baseline WHERE baseline MATCH ? '
                                        'ORDER BY bm25(baseline),id LIMIT 5', (match,)).fetchall()
                baseline = [{k: chunks[r[0]][k] for k in ('id', 'path', 'start', 'end', 'title')} |
                            {'score': 0, 'snippet': kb.excerpt(chunks[r[0]]['body'], case['query']),
                             'file_id': kb.ident('f', chunks[r[0]]['path'])} for r in matches]
                baseline_text = kb.pack({'snapshot': meta['fingerprint'], 'untrusted_source': True,
                                         'query': case['query']}, baseline, 900)
                baseline_results = json.loads(baseline_text)['results']
                def rank(results):
                    return next((i for i, r in enumerate(results, 1) if r['id'] in gold), None)
                source_bytes = full_bytes = 0
                if response['results']:
                    first = response['results'][0]
                    show_text, shown = invoke(repo, out, 'show', id=first['id'], budget=1200)
                    original = kb.safe_path(repo, first['path']).read_bytes()
                    lines = original.decode().splitlines()
                    if shown['sha256'] != kb.digest(original):
                        raise RuntimeError('source hash mismatch')
                    if any(r['text'] != lines[r['line'] - 1] for r in shown['results']):
                        raise RuntimeError('source line mismatch')
                    source_bytes, full_bytes = len(show_text.encode()), len(original)
                    invoke(repo, out, 'neighbors', id=first['id'], budget=700)
                rows.append({**case, 'skill_rank': rank(response['results']),
                             'baseline_rank': rank(baseline_results),
                             'returned_results': len(response['results']),
                             'query_bytes': len(query_text.encode()), 'first_excerpt_bytes': source_bytes,
                             'same_first_hit_full_file_bytes': full_bytes,
                             'top_titles': [r['title'] for r in response['results']]})
        link_count = 0
        for card in folder.rglob('*.md'):
            for target in re.findall(r'\]\(([^)]+)\)', card.read_text()):
                if not (card.parent / unquote(target)).resolve().exists():
                    raise RuntimeError('broken navigation link: ' + target)
                link_count += 1
        def metrics(key):
            ranks = [r[key] for r in rows]
            return {'hit_at_1': sum(r == 1 for r in ranks) / len(ranks),
                    'hit_at_5': sum(r is not None for r in ranks) / len(ranks),
                    'mrr_at_5': sum(1 / r for r in ranks if r) / len(ranks)}
        return {'repository': fixture['repository'], 'commit': fixture['commit'], 'scope': scope,
                'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                'files': built['files'], 'source_bytes': built['bytes'], 'chunks': built['chunks'],
                'edge_kinds': dict(Counter(e['kind'] for e in edges)),
                'build_seconds': elapsed, 'no_op_reindexed': again['reindexed'],
                'verified_navigation_links': link_count, 'all_edge_endpoints_valid': True,
                'retrieval_budgets_and_shown_source_verified': True,
                'skill': metrics('skill_rank'), 'body_only_fts5_baseline': metrics('baseline_rank'),
                'query_plus_first_excerpt_bytes': sum(r['query_bytes'] + r['first_excerpt_bytes'] for r in rows),
                'same_first_hit_full_files_bytes': sum(r['same_first_hit_full_file_bytes'] for r in rows),
                'limitations': ['Authored smoke set; no held-out or agent task-success evaluation.',
                                'Byte counts are not model-token counts; exclude skill/build/prompt overhead.',
                                'First excerpt may be incomplete; whole-file comparison is a cost illustration, not equal-answer proof.',
                                'Baseline is plain body-only FTS5, not tuned grep or semantic retrieval.',
                                'Subset results do not establish full-repository performance.' if scope == 'subset' else
                                'Full-scope indexing still applies documented exclusions.'],
                'cases': rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--scope', choices=('subset', 'full'), required=True)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.repo.resolve(), args.scope)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
        return 0
    except (kb.KBError, OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(2, 'evaluation: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
