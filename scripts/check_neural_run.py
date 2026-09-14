"""Validate v2 run evidence. Backend execution and task success are separate results.

This checks consistency of saved records, not their authenticity against a
malicious producer, and does not rerun the submitted code or contact an LLM.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flycoder.controller import Controller
from flycoder.state import Action, State, reward_for

SCHEMA = 'flycoder.run.v2'
NAMES = [a.value for a in Action]


class EvidenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def number(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def check_state_record(state):
    require(isinstance(state, dict) and set(state) == set(State().snapshot()), 'Invalid state record')
    for key in ['read', 'edited', 'tested', 'passed', 'timed_out']:
        require(type(state[key]) is bool, 'State flags must be booleans')
    for key in ['step', 'attempts', 'retries', 'changed_files']:
        require(integer(state[key]), 'Invalid state counter')
    require(state['last_action'] is None or state['last_action'] in NAMES, 'Invalid last action')
    require(type(state['reward']) in (int, float) and math.isfinite(state['reward']), 'Invalid reward')


def load_json(text):
    def reject(value):
        raise EvidenceError('Nonfinite JSON constant: ' + value)
    return json.loads(text, parse_constant=reject)


def newest_summary(runs_dir):
    files = list(runs_dir.glob('*/summary.json'))
    require(bool(files), 'No run summary found under ' + str(runs_dir))
    return max(files, key=lambda p: p.stat().st_mtime)


def check_trace(trace, step):
    require(isinstance(trace, dict), 'Missing current neural trace')
    require(trace.get('backend') == 'MaleCNS/DOOMFLY fixed-weight NativeBrain', 'Unexpected backend')
    require(trace.get('control') == 'intact', 'Expected intact control')
    require(trace.get('call') == step, 'Stale or out-of-order neural trace')
    require(number(trace.get('simulated_ms')) and trace['simulated_ms'] > 0, 'Invalid simulated time')
    require(number(trace.get('cumulative_simulated_ms')) and trace['cumulative_simulated_ms'] == step * trace['simulated_ms'], 'Inconsistent cumulative neural time')
    require(integer(trace.get('total_spikes')), 'Invalid spike count')
    require(integer(trace.get('neurons'), 1) and integer(trace.get('edges'), 1), 'Missing graph dimensions')
    require(trace.get('weight_learning') is False, 'Unexpected learning claim')
    for key in ['spikes_sha256', 'graph_sha256', 'stimulus_sha256', 'mapping_sha256']:
        require(sha(trace.get(key)), 'Invalid ' + key)
    scores = trace.get('scores_hz')
    require(isinstance(scores, dict) and set(scores) == set(NAMES), 'Scores must cover all five actions')
    require(all(number(v) for v in scores.values()), 'Invalid action scores')
    provenance = trace.get('provenance')
    require(isinstance(provenance, dict), 'Missing platform/kernel provenance')
    for key in ['kernel_source_sha256', 'kernel_binary_sha256']:
        require(sha(provenance.get(key)), 'Invalid ' + key)
    for key in ['platform', 'machine', 'python', 'numpy']:
        require(isinstance(provenance.get(key), str) and bool(provenance[key]), 'Missing ' + key)
    sizes, spikes = provenance.get('readout_sizes'), trace.get('readout_spikes')
    require(isinstance(sizes, dict) and isinstance(spikes, dict) and set(sizes) == set(spikes) == set(NAMES), 'Missing readout counts')
    for action in NAMES:
        require(integer(sizes[action], 1) and integer(spikes[action]), 'Invalid readout count')
        expected = spikes[action] / sizes[action] * 1000 / trace['simulated_ms']
        require(math.isclose(scores[action], expected, rel_tol=1e-12, abs_tol=1e-12), 'Rate does not match readout spike count')
    return (trace['graph_sha256'], trace['mapping_sha256'], trace['neurons'], trace['edges'], provenance)


def check_decision(decision, trace, observation, allowed, action=None):
    require(isinstance(decision, dict), 'Missing current neural decision')
    require(decision.get('observation') == observation and decision.get('allowed') == allowed, 'Decision input/mask mismatch')
    require(decision.get('scores_hz') == trace['scores_hz'], 'Decision scores differ from trace')
    scores = trace['scores_hz']
    if decision.get('reason') == 'silent_readouts' and action is None:
        require(decision.get('status') == 'rejected' and decision.get('selected_action') is None, 'Silent readout was selected')
        require(all(v == 0 for v in scores.values()), 'Silence claim contradicts readouts')
        return
    require(bool(allowed), 'Decision has no legal actions')
    best = max(scores[a] for a in allowed)
    ties = [a for a in allowed if scores[a] == best]
    ordered = sorted((scores[a] for a in allowed), reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) > 1 else None
    require(decision.get('best_score_hz') == best and decision.get('top_margin_hz') == margin, 'Incorrect best score or margin')
    require(decision.get('tied_actions') == ties, 'Incorrect tied action set')
    if action is not None:
        require(decision.get('status') == 'selected' and decision.get('reason') is None, 'Action has rejected decision')
        require(len(ties) == 1 and action == ties[0], 'Action is not a unique legal maximum')
        require(decision.get('selected_action') == trace.get('selected_action') == action, 'Selected action mismatch')
    else:
        require(decision.get('status') == 'rejected' and decision.get('reason') == 'tied_scores', 'Unknown policy rejection')
        require(decision.get('selected_action') is None and len(ties) > 1, 'Tie claim contradicts scores')


def check_tests(detail):
    require(isinstance(detail, dict), 'Missing test result')
    for key in ['passed', 'timed_out']:
        require(type(detail.get(key)) is bool, 'Invalid test ' + key)
    require(integer(detail.get('tests_run')) and integer(detail.get('tests_skipped')), 'Missing test/skip counts')
    require(detail['tests_skipped'] <= detail['tests_run'], 'More skipped than discovered tests')
    require(type(detail.get('returncode')) is int, 'Missing test return code')
    if detail['passed']:
        require(detail['returncode'] == 0 and not detail['timed_out'], 'Passing result contradicts process exit')
        require(detail['tests_run'] > detail['tests_skipped'], 'No tests actually executed')
        output = detail.get('output')
        require(isinstance(output, str), 'Missing test output')
        counts = re.findall(r'^Ran (\d+) tests? in ', output, re.MULTILINE)
        require(bool(counts) and int(counts[-1]) == detail['tests_run'], 'Test count differs from unittest output')
        skipped = re.findall(r'skipped=(\d+)', output)
        require((int(skipped[-1]) if skipped else 0) == detail['tests_skipped'], 'Skip count differs from unittest output')
        require(re.search(r'^OK(?:\s*\([^\n]*\))?\s*$', output, re.MULTILINE), 'Passing unittest footer missing')


def validate_run(summary_path):
    summary_path = Path(summary_path)
    summary = load_json(summary_path.read_text())
    events = [load_json(line) for line in (summary_path.parent / 'events.jsonl').read_text().splitlines() if line.strip()]
    require(isinstance(summary, dict) and summary.get('schema') == SCHEMA, 'Run lacks v2 evidence; rerun with current code')
    require(summary.get('policy') == 'NeuralConnectome', 'Summary is not a neural run')
    check_state_record(summary.get('state'))
    require(integer(summary.get('max_steps'), 1) and integer(summary.get('max_attempts'), 1), 'Missing budgets')
    require(type(summary.get('explore_actions')) is bool and type(summary.get('seed')) is int, 'Missing action-mask configuration')
    require(bool(events) and isinstance(events[0], dict) and events[0].get('event') == 'baseline', 'Missing initial baseline')
    for index, event in enumerate(events, 1):
        require(isinstance(event, dict) and event.get('schema') == SCHEMA and event.get('event_index') == index, 'Broken event order/schema')
    baseline = events[0]
    check_tests(baseline)
    fingerprint = baseline.get('repo_fingerprint')
    require(sha(fingerprint), 'Missing baseline fingerprint')
    replay = Controller(None, None, None, None, '', Path('.'), summary['max_steps'], summary['max_attempts'], summary['explore_actions'], summary['seed'])
    state = replay.state
    actions = 0
    tested_fingerprint = None
    last_trace = last_decision = identity = rejection = None
    done = False
    for position, event in enumerate(events[1:], 1):
        require(not done and rejection is None, 'Events appear after terminal event')
        state.step = actions + 1
        require(state.step <= summary['max_steps'], 'Action exceeds step budget')
        allowed = [a.value for a in replay.allowed()]
        observation = state.encode(summary['max_steps'], summary['max_attempts'])
        check_state_record(event.get('state'))
        require(event.get('observation') == observation and event.get('allowed') == allowed, 'Event state input or legal mask mismatch')
        trace, decision = event.get('neural_trace'), event.get('neural_decision')
        current_identity = check_trace(trace, state.step)
        if identity is None:
            identity = deepcopy(current_identity)
        require(current_identity == identity, 'Graph/mapping/kernel identity changed within run')
        require(sha(event.get('repo_fingerprint')), 'Missing event fingerprint')
        if event.get('event') == 'error':
            require(event.get('phase') == 'select', 'Infrastructure/executor error is not a policy outcome')
            require(event.get('state') == state.snapshot(), 'Error state is not current selection state')
            require(event['repo_fingerprint'] == fingerprint, 'Files changed during selection failure')
            check_decision(decision, trace, observation, allowed)
            rejection = decision['reason']
            expected_message = {'tied_scores': 'Legal neural action scores are tied; no rule fallback',
                                'silent_readouts': 'Neural readouts are silent; no mock fallback'}[rejection]
            require(event.get('message') == expected_message and summary.get('reason') == expected_message, 'Policy reason/evidence mismatch')
        else:
            require(event.get('event') == 'action', 'Unknown event type')
            name = event.get('action')
            require(name in allowed, 'Illegal action')
            check_decision(decision, trace, observation, allowed, name)
            action = Action(name)
            detail = event.get('detail', {})
            require(isinstance(detail, dict), 'Invalid action detail')
            if action != Action.EDIT:
                require(event['repo_fingerprint'] == fingerprint, 'Tracked files changed outside EDIT')
            if action == Action.READ:
                state.read = True
            elif action == Action.EDIT:
                state.attempts += 1
                state.edited, state.tested, state.passed, state.timed_out = True, False, False, False
                tested_fingerprint = None
            elif action == Action.TEST:
                check_tests(detail)
                require(detail.get('fingerprint_before') == detail.get('fingerprint_after') == fingerprint, 'TEST fingerprint mismatch')
                state.tested, state.passed, state.timed_out = True, detail['passed'], detail['timed_out']
                tested_fingerprint = fingerprint
            elif action == Action.RETRY:
                state.retries += 1
                state.edited, state.tested, state.passed, state.timed_out = False, False, False, False
                tested_fingerprint = None
            elif action == Action.DONE:
                require(state.tested and state.passed and tested_fingerprint == fingerprint, 'DONE lacks passing current tests')
                require(detail.get('tested_fingerprint') == detail.get('repo_fingerprint') == fingerprint, 'DONE fingerprint mismatch')
                done = True
            fingerprint = event['repo_fingerprint']
            recorded_state = event.get('state', {})
            require(integer(recorded_state.get('changed_files')), 'Invalid changed-file count')
            state.changed_files = recorded_state['changed_files']
            state.last_action = name
            state.reward = reward_for(action, state)
            require(recorded_state == state.snapshot(), 'Recorded action state contradicts replay')
            actions += 1
        last_trace, last_decision = trace, decision
    status = summary.get('status')
    if done:
        require(status == 'done' and actions >= 4, 'Invalid successful terminal state')
        outcome = 'task_solved'
    elif rejection:
        require(status == 'error', 'Policy rejection mislabeled as success')
        outcome = rejection
    else:
        require(status == 'exhausted' and actions > 0, 'Missing terminal success or evidenced policy outcome')
        if summary.get('reason') == 'Step budget exhausted':
            require(actions == summary['max_steps'], 'Step budget was not exhausted')
        elif summary.get('reason') == 'Edit attempt budget exhausted':
            state.step = actions + 1
            require(state.step <= summary['max_steps'] and not replay.allowed(), 'Edit budget was not exhausted')
        else:
            raise EvidenceError('Unknown exhaustion reason')
        outcome = 'budget_exhausted'
    require(summary.get('state') == state.snapshot(), 'Summary state contradicts events')
    require(summary.get('repo_fingerprint') == fingerprint and summary.get('tested_fingerprint') == tested_fingerprint, 'Summary fingerprint mismatch')
    require(summary.get('last_neural_trace') == last_trace and summary.get('last_neural_decision') == last_decision, 'Summary contains stale neural evidence')
    return {'backend_verified': True, 'task_solved': done, 'outcome': outcome,
            'completed_actions': actions, 'selection_attempts': actions + int(rejection is not None)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=Path, default=ROOT / 'runs')
    parser.add_argument('--summary', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--require-done', action='store_true', help='Fail when backend ran but did not solve the task')
    args = parser.parse_args()
    try:
        report = validate_run(args.summary or newest_summary(args.runs))
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        report = {'backend_verified': False, 'task_solved': False, 'outcome': 'invalid_evidence', 'reason': str(exc)}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    if report['backend_verified'] and not report['task_solved']:
        print('::warning::Backend execution verified; task was not solved: ' + report['outcome'])
    return 0 if report['backend_verified'] and (report['task_solved'] or not args.require_done) else 1


if __name__ == '__main__':
    raise SystemExit(main())
