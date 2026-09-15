"""Run external fixture-free bug tasks in the local neural container, then review them.

This chains the loop that used to be typed by hand: prepare an immutable task
copy, build the image once, run each (task, seed) inside the container, copy the
evidence back out of the named volume, strict-check it, render a per-run review
report, and write a batch summary.

The source tasks live outside this repository and are never modified: only the
copy under the output directory is executed. The generated fix is never merged;
it stays as evidence for human review.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_neural_run import EvidenceError, validate_run
from report_run import generate_report

COMPOSE_FILES = ['-f', 'docker-compose.neural.yml', '-f', 'docker-compose.local.yml']
SERVICE = 'flycoder-neural'
EXCLUDED_NAMES = ('fixed.py',)
NUMBER_WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six',
                7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten', 11: 'eleven',
                12: 'twelve'}

WRAPPER = '''"""Execute the {word} unchanged, fixture-free upstream test functions."""
import unittest
import test as original


def load_tests(loader, tests, pattern):
    names = sorted(name for name in vars(original) if name.startswith("test_"))
    if len(names) != {count}:
        raise RuntimeError("Expected exactly {word} upstream tests")
    return unittest.TestSuite(unittest.FunctionTestCase(getattr(original, name)) for name in names)
'''


def echo(command):
    print('+ ' + ' '.join(str(part) for part in command), flush=True)


def run_command(command, **kwargs):
    echo(command)
    return subprocess.run([str(part) for part in command], **kwargs)


def compose(arguments, **kwargs):
    return run_command(compose_command(arguments), cwd=str(ROOT), **kwargs)


def compose_command(arguments):
    """The docker compose argv without running it."""
    return ['docker', 'compose', *COMPOSE_FILES, *arguments]


def count_test_functions(test_file):
    """Names of the top-level test_* functions in an upstream test module."""
    tree = ast.parse(Path(test_file).read_text())
    return sorted(node.name for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'))


def wrapper_source(count):
    word = NUMBER_WORDS.get(count, str(count))
    return WRAPPER.format(count=count, word=word)


def sha256(path):
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def prepare_task(task_dir, destination):
    """Copy one task into an immutable run copy plus a unittest wrapper."""
    task_dir = Path(task_dir)
    destination = Path(destination)
    tests = count_test_functions(task_dir / 'test.py')
    if not tests:
        raise ValueError(f'{task_dir}: no top-level test_* functions to wrap')
    destination.mkdir(parents=True)
    digest = {}
    for source in sorted(task_dir.rglob('*')):
        if source.is_dir() or source.name in EXCLUDED_NAMES:
            continue
        if any(part.startswith('.') or part == '__pycache__'
               for part in source.relative_to(task_dir).parts):
            continue
        target = destination / source.relative_to(task_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digest[str(source.relative_to(task_dir))] = sha256(source)
    test_dir = destination / 'tests'
    test_dir.mkdir(exist_ok=True)
    (test_dir / 'test_original.py').write_text(wrapper_source(len(tests)))
    manifest = {'source': str(task_dir.resolve()),
                'test_functions': tests,
                'sha256': digest,
                'excluded': list(EXCLUDED_NAMES)}
    (destination / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def baseline_check(input_dir, expected_tests):
    """Run the untouched copy once; a broken intake must fail before the LLM is paid."""
    result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover',
                             '-s', 'tests', '-v'],
                            cwd=str(input_dir), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    output = result.stdout
    match = [int(n) for n in re.findall(r'^Ran (\d+) tests? in ', output, re.MULTILINE)]
    ran = match[-1] if match else 0
    if ran != expected_tests:
        raise ValueError(f'{input_dir}: the wrapper ran {ran} of {expected_tests} '
                         f'expected tests\n{output}')
    return {'passed': result.returncode == 0, 'tests_run': ran, 'output': output}


def plan_runs(task_ids, seeds, limit=None):
    runs = [(task, seed) for task in task_ids for seed in seeds]
    return runs[:limit] if limit else runs


def resolve_model(summary, fallback, ledger):
    """Per-run model when the evidence records one, else the host value it inherited."""
    model = summary.get('llm_model')
    if isinstance(model, str) and model.strip():
        return model
    if fallback:
        ledger['model_from_env'] = True
    return fallback


def run_one(name, seed, input_dir, remote_runs, log_path, args):
    command = compose_command(['run', '--rm', '-T', '--name', name, SERVICE,
                               '--llm', args.llm, '--repo', '/workspace',
                               '--seed', str(seed), '--runs', remote_runs,
                               '--tie-extra-windows', str(args.tie_extra_windows),
                               '--max-steps', str(args.max_steps),
                               '--max-attempts', str(args.max_attempts)])
    for editable in args.editable:
        command.append('--editable')
        command.append(editable)
    environment = os.environ.copy()
    environment['FLYCODER_TARGET_REPO'] = str(input_dir)
    environment['LLM_TIMEOUT'] = str(args.llm_timeout)
    environment['MAX_STEPS'] = str(args.max_steps)
    environment['MAX_ATTEMPTS'] = str(args.max_attempts)
    if args.dry_run:
        echo(command)
        return {'status': 'dry_run'}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('w') as log:
        try:
            result = subprocess.run([str(part) for part in command], cwd=str(ROOT),
                                    env=environment, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=args.run_timeout)
        except subprocess.TimeoutExpired:
            run_command(['docker', 'rm', '-f', name], check=False)
            return {'status': 'run_timeout'}
    return {'status': 'exited', 'returncode': result.returncode}


def export_runs(remote_runs_dir, destination):
    """Copy one container-side run directory out of the named volume."""
    destination.mkdir(parents=True, exist_ok=True)
    # Docker treats a relative --volume source as a named volume, so the host side
    # must always be absolute here.
    result = compose(['run', '--rm', '-T', '--no-deps', '--user', '0',
                      '--entrypoint', 'sh', '--volume', f'{Path(destination).resolve()}:/out',
                      SERVICE, '-c', f'cp -r {remote_runs_dir}/. /out/'],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise RuntimeError('evidence export failed:\n' + result.stdout)
    return result.stdout.strip()


def review_run(run_dir):
    """Strict-check one evidence directory and write its review report next to it."""
    run_dir = Path(run_dir)
    try:
        report = validate_run(run_dir / 'summary.json')
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        report = {'backend_verified': False, 'task_solved': False,
                  'outcome': 'invalid_evidence', 'reason': str(exc)}
    check_path = run_dir / 'check.json'
    check_path.write_text(json.dumps(report, indent=2) + '\n')
    (run_dir / 'review.md').write_text(generate_report(run_dir, check_path) + '\n')
    return report


def batch_summary_markdown(batch, rows):
    solved = [r for r in rows if r.get('outcome') == 'task_solved']
    stopped = [r for r in rows if r.get('outcome') in
               ('tied_scores', 'readout_silence', 'budget_exhausted')]
    broken = [r for r in rows if r.get('outcome') in ('coding_error', 'invalid_evidence',
                                                      'run_timeout')]
    lines = [f'# FlyCoder task bench {batch}', '',
             f'Runs: {len(rows)} | solved: {len(solved)} | policy stops: {len(stopped)} '
             f'| needs attention: {len(broken)}', '']
    models = sorted({r['llm_model'] for r in rows if r.get('llm_model')})
    if models:
        lines.extend([f'Model: `{", ".join(models)}`', ''])
    if broken:
        lines.extend(['A coding error, timeout, or invalid evidence is not a policy '
                      'result and must be read on its own.', ''])
    lines.extend(['| task | seed | outcome | steps | llm calls | tokens in/out | flags |',
                  '| --- | --- | --- | --- | --- | --- | --- |'])
    for row in rows:
        usage = row.get('usage') or {}
        tokens = (f'{usage["input_tokens"]:,} / {usage["output_tokens"]:,}'
                  if usage else '—')
        lines.append('| {task} | {seed} | {outcome} | {steps} | {calls} | {tokens} | '
                     '{flags} |'.format(task=row.get('task', '?'), seed=row.get('seed', '?'),
                                        outcome=row.get('outcome', row.get('status', '?')),
                                        steps=row.get('actions', '—'),
                                        calls=row.get('llm_calls', '—'), tokens=tokens,
                                        flags=len(row.get('review_flags', []))))
    lines.append('')
    flagged = [(r, f) for r in rows for f in r.get('review_flags', [])]
    if flagged:
        lines.extend(['## Review flags', ''])
        for row, flag in flagged:
            lines.append(f'- `{row["task"]}` seed {row["seed"]}: {flag}')
        lines.append('')
        lines.append('Passing tests are necessary but not sufficient to merge; every flag '
                     'above still needs a human decision.')
    else:
        lines.extend(['## Review flags', '',
                      '_None: no run touched a test file, changed a signature, or added an '
                      'untested definition._'])
    lines.extend(['', 'Per-run detail: `runs/<task>-seed<n>/<run-id>/review.md`.', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True,
                        help='Directory holding <task>/buggy.py + test.py + task.json')
    parser.add_argument('--ids', nargs='+', help='Task directory names; default all')
    parser.add_argument('--output', type=Path, default=ROOT / 'research' / 'bug-bench-runs')
    parser.add_argument('--batch', help='Batch name; default is a timestamp')
    parser.add_argument('--seeds', nargs='+', type=int, default=[0])
    parser.add_argument('--editable', action='append', default=None,
                        help='Editable file inside the task; repeat as needed')
    parser.add_argument('--llm', default='chat-completions')
    parser.add_argument('--llm-timeout', type=int, default=120)
    parser.add_argument('--tie-extra-windows', type=int, choices=[0, 1, 2], default=2)
    parser.add_argument('--max-steps', type=int, default=12)
    parser.add_argument('--max-attempts', type=int, default=3)
    parser.add_argument('--run-timeout', type=int, default=1800,
                        help='Seconds allowed per container run')
    parser.add_argument('--max-http-requests', type=int, default=0,
                        help='Stop starting new runs once this many HTTP attempts are '
                             'recorded; 0 means unlimited')
    parser.add_argument('--limit', type=int, help='Run at most this many task/seed pairs')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--no-baseline-check', action='store_true',
                        help='Skip the local pre-flight run of the untouched copy')
    parser.add_argument('--require-done', action='store_true',
                        help='Non-zero exit unless every run solved the task')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true', help='Reuse an existing batch name')
    args = parser.parse_args()
    args.editable = args.editable or ['buggy.py']

    batch = args.batch or datetime.now().strftime('%Y%m%d-%H%M%S')
    batch_dir = args.output / batch
    if batch_dir.exists() and not (args.force or args.dry_run):
        parser.error(f'{batch_dir} already exists; pick another --batch or pass --force')

    source = args.source.resolve()
    available = sorted(path.name for path in source.iterdir()
                       if (path / 'task.json').is_file())
    if not available:
        parser.error(f'no <task>/task.json under {source}')
    task_ids = args.ids or available
    unknown = [task for task in task_ids if task not in available]
    if unknown:
        parser.error(f'unknown task(s) {unknown}; available: {available}')

    planned = plan_runs(task_ids, args.seeds, args.limit)
    inputs = batch_dir / 'inputs'
    runs_root = batch_dir / 'runs'
    logs = batch_dir / 'logs'

    rows = []
    ledger = {'http_attempts': 0}
    # Runs made before per-run model recording still deserve a labeled model value.
    fallback_model = (os.environ.get('LLM_MODEL') or '').strip() or None
    ledger['model_from_env'] = False
    inputs.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)
    manifests = {}
    for task in task_ids:
        if not any(planned_task == task for planned_task, _ in planned):
            continue
        destination = inputs / task
        if destination.exists():
            shutil.rmtree(destination)
        manifests[task] = prepare_task(source / task, destination)
        print(f'{task}: {len(manifests[task]["test_functions"])} upstream tests wrapped',
              flush=True)
        if args.no_baseline_check:
            continue
        baseline = baseline_check(destination, len(manifests[task]['test_functions']))
        if baseline['passed']:
            parser.error(f'{task}: the untouched copy already passes its tests; '
                         'there is no bug to fix')
        print(f'{task}: baseline runs {baseline["tests_run"]} tests and fails as expected',
              flush=True)

    if not args.no_build and not args.dry_run:
        compose(['build', SERVICE], check=True)

    stopped_reason = None
    for task, seed in planned:
        if args.max_http_requests and ledger['http_attempts'] >= args.max_http_requests:
            stopped_reason = (f'HTTP attempt budget reached ({ledger["http_attempts"]}/'
                              f'{args.max_http_requests}); remaining runs were not started')
            print(stopped_reason, flush=True)
            break
        label = f'{task}-seed{seed}'
        remote = f'/data/runs/{batch}/{label}'
        log_path = logs / f'{label}.log'
        print(f'=== {label}', flush=True)
        outcome = run_one(f'flycoder-{batch}-{label}', seed, inputs / task, remote,
                          log_path, args)
        row = {'task': task, 'seed': seed, 'batch': batch,
               'log': str(log_path.relative_to(batch_dir)),
               'run': outcome.get('status')}
        if outcome.get('status') == 'dry_run':
            rows.append(row)
            continue
        run_dir = runs_root / label
        if outcome.get('status') == 'run_timeout':
            row['outcome'] = 'run_timeout'
            rows.append(row)
            continue
        export_runs(remote, run_dir)
        summaries = sorted(run_dir.glob('*/summary.json'))
        if len(summaries) != 1:
            row['outcome'] = 'invalid_evidence'
            row['reason'] = f'expected one run directory, found {len(summaries)}'
            rows.append(row)
            continue
        evidence_dir = summaries[0].parent
        report = review_run(evidence_dir)
        summary = json.loads((evidence_dir / 'summary.json').read_text())
        usage_records = [u for u in summary.get('llm_usage', []) if isinstance(u, dict)]
        usage = {'input_tokens': sum(u.get('input_tokens', 0) for u in usage_records),
                 'output_tokens': sum(u.get('output_tokens', 0) for u in usage_records)}
        ledger['http_attempts'] += summary.get('llm_http_attempts', 0)
        row.update({key: report.get(key) for key in ('outcome', 'task_solved',
                                                     'backend_verified')})
        row.update({'actions': report.get('completed_actions'),
                    'llm_calls': summary.get('llm_calls', 0),
                    'llm_model': resolve_model(summary, fallback_model, ledger),
                    'usage': usage if usage_records else None,
                    'review_flags': [line.strip() for line in
                                     (evidence_dir / 'review.md').read_text().splitlines()
                                     if line.startswith('- ⚠️') or line.startswith('- ℹ️')],
                    'run_dir': str(evidence_dir.relative_to(batch_dir))})
        rows.append(row)
        print(f'=== {label}: {row["outcome"]} ({row.get("actions", "?")} actions)', flush=True)

    batch_report = {'schema': 'flycoder.task-bench.v1', 'batch': batch,
                    'source': str(source), 'tasks': task_ids, 'seeds': args.seeds,
                    'llm': args.llm,
                    'llm_models': sorted({row['llm_model'] for row in rows
                                          if row.get('llm_model')}),
                    'llm_model_source': ('host LLM_MODEL at batch time (runs predate '
                                         'per-run model recording)'
                                         if ledger['model_from_env']
                                         else 'per-run summary.json'),
                    'tie_extra_windows': args.tie_extra_windows,
                    'max_steps': args.max_steps, 'max_attempts': args.max_attempts,
                    'llm_timeout_seconds': args.llm_timeout,
                    'manifests': manifests, 'http_attempts': ledger['http_attempts'],
                    'stopped_reason': stopped_reason, 'results': rows,
                    'limitations': 'Small sample: one run per (task, seed). A policy stop '
                                   'is a legal controller outcome, not infrastructure '
                                   'failure. Fixes are evidence only and are never merged.'}
    if not args.dry_run:
        (batch_dir / 'batch.json').write_text(json.dumps(batch_report, indent=2) + '\n')
        (batch_dir / 'summary.md').write_text(batch_summary_markdown(batch, rows) + '\n')
        print((batch_dir / 'summary.md').read_text(), flush=True)

    if any(row.get('outcome') in ('run_timeout', 'invalid_evidence') for row in rows):
        return 2
    unsolved = [row for row in rows if not row.get('task_solved')]
    if args.require_done and unsolved:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
