"""Real-data replay, stimulus ablation, and disconnection validation."""
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flycoder.malecns import MaleCNSBackend
from flycoder.state import State

observations = [State().encode(12, 3)['features'],
                State(read=True, last_action='READ').encode(12, 3)['features'],
                State(read=True, edited=True, attempts=1, last_action='EDIT').encode(12, 3)['features']]
traces = {}
for name, control in [('intact', 'intact'), ('replay', 'intact'), ('no-stimulus', 'no-stimulus'), ('disconnected', 'disconnected'), ('shuffled-readout', 'shuffled-readout')]:
    backend = MaleCNSBackend(control=control)
    backend.reset(0)
    rows = []
    for features in observations:
        backend.stimulate_and_step(features)
        rows.append(dict(backend.last_trace))
    backend.close()
    traces[name] = rows
assert [r['spikes_sha256'] for r in traces['intact']] == [r['spikes_sha256'] for r in traces['replay']]
assert [r['spikes_sha256'] for r in traces['intact']] != [r['spikes_sha256'] for r in traces['no-stimulus']]
assert all(all(v == 0 for v in r['scores_hz'].values()) for r in traces['disconnected'])
assert any(a['scores_hz'] != b['scores_hz'] for a,b in zip(traces['intact'], traces['shuffled-readout']))
(ROOT / 'research/neural-validation.json').write_text(json.dumps({'passed': True, 'traces': traces}, indent=2) + '\n')
print('Full-graph replay, stimulus ablation, disconnection and readout controls passed.')
