"""Assert that an offline run was actually driven by the real connectome.

Linux CI runs the MaleCNS/DOOMFLY backend end to end. The fixed-weight policy
is allowed to fail the toy task (ties and budget exhaustion are documented
policy outcomes, not backend failures); this script distinguishes the two so a
green job still means "the native backend ran", never "the policy looked good".
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flycoder.state import Action  # noqa: E402

# These reasons describe policy quality, not infrastructure. Anything else is a failure.
# Matched as prefixes: the controller appends detail such as '; no rule fallback'.
POLICY_OUTCOMES = (
    'Legal neural action scores are tied',
    'Edit attempt budget exhausted',
    'Step budget exhausted',
)
ACTION_NAMES = [a.value for a in Action]


def newest_summary(runs_dir: Path) -> Path:
    summaries = sorted(runs_dir.glob('*/summary.json'), key=lambda p: p.stat().st_mtime)
    if not summaries:
        raise SystemExit('No run summary found under ' + str(runs_dir))
    return summaries[-1]


def check_trace(label: str, trace) -> None:
    if not isinstance(trace, dict):
        raise SystemExit(f'{label}: missing neural trace')
    backend = str(trace.get('backend', ''))
    if 'MaleCNS' not in backend or 'DOOMFLY' not in backend:
        raise SystemExit(f'{label}: unexpected backend {backend!r}')
    if trace.get('control') != 'intact':
        raise SystemExit(f'{label}: expected intact control, got {trace.get("control")!r}')
    if not float(trace.get('simulated_ms', 0)) > 0:
        raise SystemExit(f'{label}: no simulated neural time')
    for field in ('spikes_sha256', 'graph_sha256', 'stimulus_sha256'):
        if not isinstance(trace.get(field), str) or len(trace[field]) != 64:
            raise SystemExit(f'{label}: missing {field}')
    if not int(trace.get('total_spikes', 0)) > 0:
        raise SystemExit(f'{label}: readouts produced no spikes')
    scores = trace.get('scores_hz')
    if not isinstance(scores, dict) or set(scores) != set(ACTION_NAMES):
        raise SystemExit(f'{label}: scores_hz must cover every action')
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in scores.values()):
        raise SystemExit(f'{label}: non-finite action score')
    if trace.get('weight_learning') is not False:
        raise SystemExit(f'{label}: weights must not be claimed as learned')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=Path, default=ROOT / 'runs')
    parser.add_argument('--summary', type=Path)
    args = parser.parse_args()
    summary_path = args.summary or newest_summary(args.runs)
    summary = json.loads(summary_path.read_text())
    events = [json.loads(line) for line in
              (summary_path.parent / 'events.jsonl').read_text().splitlines() if line.strip()]
    actions = [e for e in events if e.get('event') == 'action']
    if not actions:
        raise SystemExit('Run executed no actions')
    for event in actions:
        check_trace(f'action {event["action"]}', event.get('neural_trace'))
    status, reason = summary.get('status'), str(summary.get('reason', ''))
    steps = len(actions)
    if status == 'done':
        print(f'neural integration: solved the toy task in {steps} actions '
              f'(real connectome trace on every action)')
        return 0
    if not any(reason.startswith(outcome) for outcome in POLICY_OUTCOMES):
        raise SystemExit(f'Infrastructure failure: status={status} reason={reason}')
    if status not in {'error', 'exhausted'}:
        raise SystemExit(f'Unexpected terminal status {status!r}')
    print(f'::warning::neural backend ran on all {steps} actions, but the fixed-weight '
          f'policy did not solve the toy task: status={status} reason={reason}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
