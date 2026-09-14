"""Controlled full-graph replay: fixed mapping and observations across platforms."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flycoder.malecns import MaleCNSBackend
from flycoder.state import State


def snapshot(brain):
    # Include graph arrays, initialized state, and numeric state after each input.
    names = ('ptr', 'post', 'weight', 'ids', 'retina', 'uv', 'lamina', 'sugar',
             'v', 'g', 'refractory', 'drive', 'previous_drive', 'queue',
             'queue_count', 'counts', 'luminance', 'active', 'active_flag',
             'nactive', 'last')
    return {name: hashlib.sha256(getattr(brain, name).tobytes()).hexdigest()
            for name in names}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'research/controlled-replay.json')
    args = parser.parse_args()
    observations = [State().encode(12, 3)['features'],
                    State(read=True, last_action='READ').encode(12, 3)['features'],
                    State(read=True, edited=True, attempts=1, last_action='EDIT').encode(12, 3)['features']]
    backend = MaleCNSBackend(mapping=ROOT / 'diagnostics/reference-map.json')
    backend.reset(0)
    result = {'schema': 'flycoder.controlled-replay.v1', 'observations': observations,
              'initial_arrays': snapshot(backend.brain), 'traces': [],
              'compiler': subprocess.check_output(['clang++', '--version'], text=True).strip()}
    for features in observations:
        backend.stimulate_and_step(features)
        result['traces'].append(dict(backend.last_trace, arrays=snapshot(backend.brain)))
    backend.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
