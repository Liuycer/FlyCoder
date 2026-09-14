"""Compare saved neural diagnostics only; no simulation or LLM calls."""
import argparse
import json
from pathlib import Path


def describe(path):
    path = Path(path)
    if path.is_dir():
        path = path / 'summary.json'
    summary = json.loads(path.read_text())
    events = [json.loads(line) for line in (path.parent / 'events.jsonl').read_text().splitlines() if line.strip()]
    attempts = []
    for event in events:
        if event.get('event') not in {'action', 'error'}:
            continue
        trace = event.get('neural_trace') or {}
        decision = event.get('neural_decision') or {}
        attempts.append({'step': event.get('state', {}).get('step'), 'event': event['event'],
                         'action': event.get('action'), 'observation': event.get('observation'),
                         'allowed': event.get('allowed'), 'scores_hz': trace.get('scores_hz'),
                         'stimulus_sha256': trace.get('stimulus_sha256'),
                         'spikes_sha256': trace.get('spikes_sha256'),
                         'readout_spikes': trace.get('readout_spikes'),
                         'tied_actions': decision.get('tied_actions'),
                         'top_margin_hz': decision.get('top_margin_hz'),
                         'reason': decision.get('reason') or event.get('message')})
    traces = [e['neural_trace'] for e in events if e.get('neural_trace')]
    first = traces[0] if traces else {}
    return {'path': str(path), 'schema': summary.get('schema', 'legacy'),
            'status': summary.get('status'), 'reason': summary.get('reason'),
            'seed': summary.get('seed'), 'graph_sha256': first.get('graph_sha256'),
            'mapping_sha256': first.get('mapping_sha256'), 'provenance': first.get('provenance'),
            'attempts': attempts}


def compare(left, right):
    a, b = describe(left), describe(right)
    findings = []
    same_graph = bool(a['graph_sha256']) and a['graph_sha256'] == b['graph_sha256']
    same_map = bool(a['mapping_sha256']) and a['mapping_sha256'] == b['mapping_sha256']
    findings.append('Graph bytes match.' if same_graph else 'Graph identity differs or is unavailable.')
    findings.append('Readout mapping bytes match.' if same_map else 'Readout mapping differs or is unavailable; scores are not a matched-decoder comparison.')
    first_divergence = None
    for index, (x, y) in enumerate(zip(a['attempts'], b['attempts']), 1):
        changed = [k for k in ['observation', 'allowed', 'stimulus_sha256', 'spikes_sha256', 'scores_hz', 'action'] if x[k] != y[k]]
        if changed:
            first_divergence = {'attempt': index, 'fields': changed, 'left': x, 'right': y}
            break
    if first_divergence:
        x, y = first_divergence['left'], first_divergence['right']
        if same_graph and x['stimulus_sha256'] and x['stimulus_sha256'] == y['stimulus_sha256'] and x['spikes_sha256'] != y['spikes_sha256']:
            findings.append('Same graph and this stimulus hash, but different spike hashes. Readout grouping alone cannot explain the spike-array difference; runtime, initial state and numerical behavior need a controlled replay.')
    if not a['provenance'] or not b['provenance']:
        findings.append('At least one run predates platform/kernel provenance logging; a specific CPU/compiler cause is not established.')
    for label, record in [('left', a), ('right', b)]:
        if record['status'] == 'error' and (not record['attempts'] or not record['attempts'][-1]['scores_hz']):
            findings.append(label + ' run lacks the failed selection scores; do not substitute the preceding action trace.')
    return {'left': a, 'right': b, 'same_graph': same_graph, 'same_mapping': same_map,
            'first_divergence': first_divergence, 'findings': findings}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = compare(args.left, args.right)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    for finding in report['findings']:
        print(finding)


if __name__ == '__main__':
    main()
