"""Generate a human-readable Markdown review report from a FlyCoder run.

The report is for review, not for machine parsing; the structured evidence
remains in summary.json, events.jsonl, and changes.patch.
"""
import argparse
import json
import sys
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text())


def load_events(run_dir):
    lines = (Path(run_dir) / 'events.jsonl').read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def trunc(text, limit=20):
    if len(text) <= limit:
        return text
    return text[:limit] + '…'


def sha_short(value):
    if isinstance(value, str) and len(value) >= 12:
        return value[:12] + '…'
    return str(value)


def verdict_line(summary, check):
    status = summary.get('status', 'unknown')
    outcome = check.get('outcome', '') if check else ''
    verified = check.get('backend_verified', False) if check else False
    if check:
        if outcome == 'task_solved' and verified:
            icon = '✅'
            label = 'task_solved — backend verified, all tests pass'
        elif verified and outcome in ('tied_scores', 'readout_silence', 'budget_exhausted'):
            icon = '⚠️'
            label = f'{outcome} — backend verified; policy stopped without solving'
        else:
            icon = '❌'
            label = f'{outcome} — backend not verified or invalid evidence'
    elif status == 'done':
        icon = '✅'
        label = 'done (no strict checker report provided)'
    else:
        icon = '❌'
        label = status
    reason = summary.get('reason', '')
    return f'{icon} **{label}**' + (f' — {reason}' if reason else '')


def format_actions(events):
    lines = []
    baseline = next((e for e in events if e.get('event') == 'baseline'), None)
    if baseline:
        status = 'OK' if baseline.get('passed') else 'FAIL'
        count = baseline.get('tests_run', '?')
        lines.append(f'0. Baseline tests: {count} run, {status}')
    for e in events:
        if e.get('event') != 'action':
            continue
        action = e.get('action', '?')
        state = e.get('state', {})
        line = f'{e["event_index"]}. {action}'
        if action == 'EDIT':
            line += f' (attempt {state.get("attempts", "?")})'
        elif action == 'TEST':
            detail = e.get('detail', {})
            run = detail.get('tests_run', '?')
            skipped = detail.get('tests_skipped', 0)
            passed = detail.get('passed', False)
            timed_out = detail.get('timed_out', False)
            mark = 'OK' if passed else ('TIMEOUT' if timed_out else 'FAIL')
            skip_note = f', {skipped} skipped' if skipped else ''
            line += f' ({run} run{skip_note}, {mark})'
        lines.append(line)
    return lines


def format_baseline_failures(baseline_event):
    if not baseline_event or baseline_event.get('passed'):
        return []
    output = baseline_event.get('output', '')
    failures = [line.strip() for line in output.splitlines()
                if line.startswith('FAIL: ') or line.startswith('ERROR: ')]
    return failures


def format_llm_usage(summary):
    calls = summary.get('llm_calls', 0)
    attempts = summary.get('llm_http_attempts', 0)
    usage = summary.get('llm_usage', [])
    if calls == 0 and attempts == 0:
        coder = summary.get('coder', '')
        if 'Mock' in coder:
            return ['Mock adapter — no LLM calls.']
        return ['Usage not recorded (run created before usage persistence).']
    total_in = sum(r.get('input_tokens', 0) for r in usage if isinstance(r, dict))
    total_out = sum(r.get('output_tokens', 0) for r in usage if isinstance(r, dict))
    retries = attempts - calls if attempts >= calls else 0
    lines = [f'Calls: {calls} | HTTP attempts: {attempts} (retries: {retries})',
             f'Tokens: input {total_in:,} / output {total_out:,}']
    for i, r in enumerate(usage, 1):
        if not isinstance(r, dict):
            continue
        parts = []
        if 'input_tokens' in r:
            parts.append(f'in {r["input_tokens"]:,}')
        if 'output_tokens' in r:
            parts.append(f'out {r["output_tokens"]:,}')
        if parts:
            lines.append(f'  request {i}: {", ".join(parts)}')
    return lines


def format_neural(summary):
    trace = summary.get('last_neural_trace')
    if not isinstance(trace, dict):
        return None
    window = trace.get('windows', [trace])[0] if trace.get('windows') else trace
    backend = window.get('backend', trace.get('backend', 'unknown'))
    neurons = window.get('neurons')
    edges = window.get('edges')
    graph_sha = window.get('graph_sha256')
    mapping_sha = window.get('mapping_sha256')
    machine = window.get('provenance', {}).get('machine', '')
    lines = [backend]
    if neurons and edges:
        lines.append(f'{neurons:,} neurons, {edges:,} edges ({machine})')
    if graph_sha:
        lines.append(f'Graph: `{sha_short(graph_sha)}`')
    if mapping_sha:
        lines.append(f'Mapping: `{sha_short(mapping_sha)}`')
    return lines


def generate_report(run_dir, check_report=None):
    run_dir = Path(run_dir)
    summary = load_json(run_dir / 'summary.json')
    events = load_events(run_dir)
    patch = (run_dir / 'changes.patch').read_text()
    check = load_json(check_report) if check_report else None

    baseline = next((e for e in events if e.get('event') == 'baseline'), None)
    lines = ['# FlyCoder run report', '',
             f'## Verdict', '', verdict_line(summary, check), '']

    lines.extend(['## Actions', ''])
    lines.extend(format_actions(events))
    lines.append('')

    if patch.strip():
        lines.extend(['## Diff', '', '```diff', patch.rstrip(), '```', ''])
    else:
        lines.extend(['## Diff', '', '_No changes._', ''])

    lines.extend(['## LLM usage', ''])
    lines.extend(format_llm_usage(summary))
    lines.append('')

    neural = format_neural(summary)
    if neural:
        lines.extend(['## Neural backend', ''])
        lines.extend(neural)
        lines.append('')

    baseline_failures = format_baseline_failures(baseline)
    if baseline_failures:
        lines.extend(['## Baseline failures (what the bug caused)', ''])
        lines.extend(f'- {f}' for f in baseline_failures)
        lines.append('')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True,
                        help='Run directory containing summary.json, events.jsonl, changes.patch')
    parser.add_argument('--check-report', type=Path,
                        help='Optional check-report.json from scripts/check_neural_run.py')
    parser.add_argument('--output', type=Path,
                        help='Write report to file; default prints to stdout')
    args = parser.parse_args()
    report = generate_report(args.run_dir, args.check_report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + '\n', encoding='utf-8')
    else:
        print(report)


if __name__ == '__main__':
    main()
