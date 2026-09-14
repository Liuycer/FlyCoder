"""Compare controlled replay inputs separately from neural output equality."""
import argparse
import json
from pathlib import Path


def compare(left, right):
    if left['schema'] != 'flycoder.controlled-replay.v1' or right['schema'] != left['schema']:
        raise ValueError('Unsupported replay schema')
    rows = []
    for i, (a, b) in enumerate(zip(left['traces'], right['traces']), 1):
        rows.append({'call': i,
                     'same_inputs': all(a[k] == b[k] for k in ('graph_sha256', 'mapping_sha256', 'stimulus_sha256', 'simulated_ms')),
                     'same_spikes': a['spikes_sha256'] == b['spikes_sha256'],
                     'same_scores': a['scores_hz'] == b['scores_hz'],
                     'different_arrays': [k for k, v in a['arrays'].items() if b['arrays'].get(k) != v]})
    inputs_match = (left['observations'] == right['observations'] and
                    left['initial_arrays'] == right['initial_arrays'] and
                    len(left['traces']) == len(right['traces']) and
                    bool(rows) and all(r['same_inputs'] for r in rows))
    return {'inputs_match': inputs_match,
            'spikes_match': inputs_match and all(r['same_spikes'] for r in rows),
            'scores_match': inputs_match and all(r['same_scores'] for r in rows),
            'initial_differences': [k for k, v in left['initial_arrays'].items() if right['initial_arrays'].get(k) != v],
            'rows': rows}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--require-equal', action='store_true')
    args = parser.parse_args()
    result = compare(json.loads(args.left.read_text()), json.loads(args.right.read_text()))
    data = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data)
    print(data, end='')
    return 1 if args.require_equal and not result['spikes_match'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
