#!/usr/bin/env python3
"""Pinned, offline before/after evaluation. Never execute target-repository code."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sqlite3
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/repo-knowledge/scripts/repo_kb.py'
MANIFEST = ROOT / 'benchmarks/universal.json'


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], timeout=120)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(repo, definition):
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != definition['commit']:
        raise ValueError('wrong revision: ' + str(repo))
    if git(repo, 'status', '--porcelain', '--untracked-files=all').strip():
        raise ValueError('evaluation checkout must be clean: ' + str(repo))
    inventory = {}
    for entry in git(repo, 'ls-files', '--stage', '-z').decode().split('\0'):
        if not entry:
            continue
        details, name = entry.split('\t')
        mode, oid, stage = details.split()
        if mode not in ('100644', '100755') or stage != '0':
            raise ValueError('unsupported evaluation Git entry: ' + name)
        raw = (repo / name).read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if actual != oid:
            raise ValueError('checkout bytes differ from Git blob (disable autocrlf): ' + name)
        inventory[name] = sha(raw)
    for name, expected in definition['source_sha256'].items():
        if inventory[name] != expected:
            raise ValueError('gold source changed: ' + name)
    return inventory


def gold_lines(repo, case):
    result = []
    for artifact in case['artifacts']:
        lines = (repo / artifact['path']).read_text(encoding='utf-8').splitlines()
        points = set()
        for start, end in artifact['ranges']:
            if not 1 <= start <= end <= len(lines):
                raise ValueError('invalid gold range: ' + case['id'])
            points.update((artifact['path'], n) for n in range(start, end + 1) if lines[n-1].strip())
        result.append(points)
    return result


def ranking(items, gold):
    seen, gains, first = set(), [], None
    for i, item in enumerate(items[:5], 1):
        hits = {j for j, artifact in enumerate(gold) if any(
            p == item['path'] and item['start'] <= n <= item['end'] for p, n in artifact)}
        if hits and first is None:
            first = i
        gains.append(1 if hits - seen else 0)
        seen |= hits
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 5)))
    return {'hit1': int(first == 1), 'mrr5': 1 / first if first else 0,
            'ndcg5': sum(g / math.log2(i + 2) for i, g in enumerate(gains)) / ideal if ideal else None,
            'artifact_recall5': len(seen) / len(gold) if gold else None,
            'first_relevant_rank': first}


def canonical(command, payload):
    """Same projection for both variants; no IDs, scores, titles, or warnings."""
    base = {'snapshot': payload.get('snapshot'), 'command': command}
    rows = payload.get('results', [])
    if command == 'show':
        base.update(path=payload['path'], sha256=payload['sha256'])
        rows = [{'start': r['line'], 'text': r['text']} for r in rows]
    elif command == 'query':
        rows = [{k: r[k] for k in ('path', 'start', 'end', 'snippet')} for r in rows]
    elif command == 'neighbors':
        rows = [{k: r[k] for k in ('path', 'kind', 'direction', 'evidence')} for r in rows]
    elif command == 'collect':
        rows = [{k: r[k] for k in ('path', 'start', 'end', 'sha256', 'text')} for r in rows]
    return encode({**base, 'results': rows, 'next_offset': payload.get('next_offset')})


def points(command, payload, repo):
    """Only actual, byte-verified source earns evidence credit, never locators."""
    found = set()
    if command == 'show':
        raw = (repo / payload['path']).read_bytes()
        if sha(raw) != payload['sha256']:
            raise ValueError('wrong show provenance')
        lines = raw.decode('utf-8').splitlines()
        for row in payload['results']:
            if row['text'] != lines[row['line'] - 1]:
                raise ValueError('wrong source line')
            if row['text'].strip():
                found.add((payload['path'], row['line']))
    elif command == 'collect':
        for row in payload['results']:
            raw = (repo / row['path']).read_bytes()
            lines = raw.decode('utf-8').splitlines()
            if sha(raw) != row['sha256'] or row['text'] != '\n'.join(lines[row['start']-1:row['end']]):
                raise ValueError('wrong collection provenance')
            found.update((row['path'], n) for n in range(row['start'], row['end']+1) if lines[n-1].strip())
    return found


def coverage(found, gold):
    union = set().union(*gold) if gold else set()
    return {'evidence_coverage': len(found & union) / len(union) if union else None,
            'artifact_coverage': sum(bool(a <= found) for a in gold) / len(gold) if gold else None,
            'evidence_precision': len(found & union) / len(found) if found and union else None}


def evaluate_case(kb, repo, out, case, tokenizer, budgets, include_collect):
    gold = gold_lines(repo, case)
    trace = []

    def invoke(command, **kwargs):
        args = argparse.Namespace(repo=str(repo), output=str(out), command=command,
                                  budget=900, limit=6, offset=0, **kwargs)
        text, code = kb.run(args)
        if code or len(text.encode()) > args.budget * 4:
            raise ValueError('invalid or over-budget response')
        payload = json.loads(text)
        projected = canonical(command, payload)
        trace.append({'command': command, 'native_tokens': len(tokenizer.encode(text, disallowed_special=())),
                      'canonical_tokens': len(tokenizer.encode(projected, disallowed_special=())),
                      'utf8_bytes': len(text.encode()), 'byte_proxy_units': math.ceil(len(text.encode()) / 4),
                      'points': points(command, payload, repo),
                      'results': len(payload['results']), 'next_offset': payload.get('next_offset')})
        return payload

    response = invoke('query', query=case['query'])
    results = response['results']
    # At most one query continuation, no gold-aware rewrites or stopping.
    if response.get('next_offset') is not None and response['next_offset'] > 0:
        args = argparse.Namespace(repo=str(repo), output=str(out), command='query',
                                  budget=900, limit=6, offset=response['next_offset'], query=case['query'])
        text, code = kb.run(args)
        if code:
            raise ValueError(text)
        payload = json.loads(text)
        trace.append({'command': 'query-page', 'native_tokens': len(tokenizer.encode(text, disallowed_special=())),
                      'canonical_tokens': len(tokenizer.encode(canonical('query', payload), disallowed_special=())),
                      'utf8_bytes': len(text.encode()), 'byte_proxy_units': math.ceil(len(text.encode()) / 4),
                      'points': set(), 'results': len(payload['results']), 'next_offset': payload.get('next_offset')})
        results = results + payload['results']
    rank = ranking(results, gold)
    # One per file first, then the remaining hits. Fixed six-excerpt limit.
    first, rest, seen = [], [], set()
    for result in results:
        (rest if result['path'] in seen else first).append(result)
        seen.add(result['path'])
    queue = (first + rest)[:6]
    for i, result in enumerate(queue):
        payload = invoke('show', id=result['id'])
        # Charge one continuation for the first two excerpts when it advances.
        if i < 2 and payload.get('next_offset'):
            args = argparse.Namespace(repo=str(repo), output=str(out), command='show',
                                      budget=900, offset=payload['next_offset'], id=result['id'])
            text, code = kb.run(args)
            if code:
                raise ValueError(text)
            page = json.loads(text)
            trace.append({'command': 'show-page', 'native_tokens': len(tokenizer.encode(text, disallowed_special=())),
                          'canonical_tokens': len(tokenizer.encode(canonical('show', page), disallowed_special=())),
                          'utf8_bytes': len(text.encode()), 'byte_proxy_units': math.ceil(len(text.encode()) / 4),
                          'points': points('show', page, repo), 'results': len(page['results']),
                          'next_offset': page.get('next_offset')})
    if queue:
        neighbors = invoke('neighbors', id=queue[0]['id'])
        visited = {r['id'] for r in queue}
        follow = [r for r in neighbors['results'] if r['id'].startswith('c-') and r['id'] not in visited]
        for result in follow[:2]:
            invoke('show', id=result['id'])
    curves, cost_at_coverage = {}, {}
    for form in ('native', 'canonical'):
        spent, found, checkpoints = 0, set(), [(0, set())]
        costs = {'0.5': None, '0.8': None, '1.0': None}
        for step in trace:
            spent += step[form + '_tokens']
            found |= step['points']
            checkpoints.append((spent, found.copy()))
            cov = coverage(found, gold)['evidence_coverage']
            for threshold in costs:
                if cov is not None and cov >= float(threshold) and costs[threshold] is None:
                    costs[threshold] = spent
        curves[form] = {str(b): {'tokens': max(s for s, _ in checkpoints if s <= b),
                                        **coverage(next(p for s, p in reversed(checkpoints) if s <= b), gold)}
                        for b in budgets}
        cost_at_coverage[form] = costs
    collected = []
    if include_collect and hasattr(kb, 'collect'):
        for budget in (400, 900, 1800, 3600):
            args = argparse.Namespace(repo=str(repo), output=str(out), command='collect',
                                      budget=budget, offset=0, limit=8, query=case['query'])
            text, code = kb.run(args)
            if code or len(text.encode()) > budget * 4:
                raise ValueError('invalid collection response')
            payload = json.loads(text)
            collected.append({'byte_budget': budget, 'native_tokens': len(tokenizer.encode(text, disallowed_special=())),
                              'canonical_tokens': len(tokenizer.encode(canonical('collect', payload), disallowed_special=())),
                              **coverage(points('collect', payload, repo), gold),
                              'assessment': payload.get('assessment'), 'stop_reason': payload.get('stop_reason')})
    return {'id': case['id'], 'kind': case['kind'], 'query': case['query'], **rank,
            'top5': [{k: r[k] for k in ('path', 'start', 'end', 'title')} for r in results[:5]],
            'negative_has_hits': bool(results) if not gold else None,
            'assessment': response.get('assessment'), 'curves': curves,
            'cost_at_coverage': cost_at_coverage, 'collect': collected,
            'trace': [{k: v for k, v in s.items() if k != 'points'} for s in trace]}


def summary(cases, budgets):
    positive = [c for c in cases if c['kind'] != 'negative']
    negative = [c for c in cases if c['kind'] == 'negative']
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    return {'positive_cases': len(positive), 'negative_cases': len(negative),
            **{k: mean([c[k] for c in positive]) for k in ('hit1', 'mrr5', 'ndcg5', 'artifact_recall5')},
            'negative_has_hits_rate': mean([c['negative_has_hits'] for c in negative]),
            'coverage': {form: {str(b): mean([c['curves'][form][str(b)]['evidence_coverage'] for c in positive])
                                for b in budgets} for form in ('native', 'canonical')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-cache', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--split', choices=('dev', 'heldout', 'all'), default='dev')
    parser.add_argument('--variant', choices=('before', 'after', 'both'), default='both')
    parser.add_argument('--collect', action='store_true', help='also measure the new collection workflow separately')
    parser.add_argument('--common-scope', action='store_true', help='also run both on the intersection of discovered paths')
    args = parser.parse_args()
    import tiktoken
    if tiktoken.__version__ != '0.12.0':
        parser.error('install benchmarks/requirements.txt (pinned tiktoken required)')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    tokenizer = tiktoken.get_encoding(manifest['tokenizer'])
    report = {'manifest_sha256': sha(MANIFEST.read_bytes()), 'baseline_commit': manifest['baseline_commit'],
              'tokenizer': manifest['tokenizer'], 'tiktoken': tiktoken.__version__,
              'python': platform.python_version(), 'platform': platform.system(), 'sqlite': sqlite3.sqlite_version,
              'implementation_sha256': sha(SCRIPT.read_bytes()), 'runs': []}
    with tempfile.TemporaryDirectory(prefix='repo-kb-benchmark-') as temp:
        temp = Path(temp)
        baseline = temp / 'before.py'
        baseline.write_bytes(git(ROOT, 'show', manifest['baseline_commit'] + ':skills/repo-knowledge/scripts/repo_kb.py'))
        before, after = load(baseline, 'kb_before'), load(SCRIPT, 'kb_after')
        for definition in manifest['repositories']:
            if args.split != 'all' and definition['split'] != args.split:
                continue
            repo = (args.repo_cache / definition['name']).resolve()
            inventory = verify(repo, definition)
            gold = [c for c in manifest['cases'] if c['repo'] == definition['name']]
            scopes = {}
            for name, kb in [('before', before), ('after', after)]:
                scopes[name] = set(kb.discover(repo, temp / 'unused', kb.settings(repo, False, False))[0])
            for scope in (['native', 'intersection'] if args.common_scope else ['native']):
                for variant, kb in [('before', before), ('after', after)]:
                    if args.variant != 'both' and variant != args.variant:
                        continue
                    out = temp / (definition['name'] + '-' + variant + '-' + scope)
                    original = kb.discover
                    if scope == 'intersection':
                        allowed = scopes['before'] & scopes['after']
                        def restricted(root, output, cfg, *a, **kw):
                            files, skipped = original(root, output, cfg, *a, **kw)
                            return {p: f for p, f in files.items() if p in allowed}, skipped
                        kb.discover = restricted
                    try:
                        start = time.perf_counter()
                        built = kb.build(repo, out)
                        elapsed = time.perf_counter() - start
                        if kb.build(repo, out)['reindexed'] != 0:
                            raise ValueError('no-op rebuild failed')
                        folder, _ = kb.current(out)
                        with closing(kb.connect(folder / 'index.sqlite3', True)) as db:
                            indexed = {r[0] for r in db.execute('SELECT path FROM files')}
                        cases = [evaluate_case(kb, repo, out, c, tokenizer, manifest['budgets'], args.collect) for c in gold]
                        run = {'repo': definition['name'], 'split': definition['split'], 'variant': variant,
                               'scope': scope, 'commit': definition['commit'], 'tracked_files': len(inventory),
                               'inventory_sha256': sha(encode(inventory).encode()), 'indexed_files': len(indexed),
                               'indexed_paths_sha256': sha(encode(sorted(indexed)).encode()),
                               'discovery_required': len(definition['discovery_required']),
                               'discovery_omissions': sorted(set(definition['discovery_required']) - indexed),
                               'skipped': built['skipped'], 'build_seconds': round(elapsed, 3),
                               'summary': summary(cases, manifest['budgets']), 'cases': cases}
                        report['runs'].append(run)
                        print(encode({k: run[k] for k in ('repo', 'variant', 'scope', 'indexed_files', 'summary')}), flush=True)
                    finally:
                        kb.discover = original
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
