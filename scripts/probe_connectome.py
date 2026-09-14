"""Full graph calibration using synthetic stimuli only, plus causal controls."""
import json
from pathlib import Path
import resource
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flycoder.malecns import native_class, GRAPH, UPSTREAM, FEATURES, ACTIONS, digest

out = ROOT / 'research'
out.mkdir(exist_ok=True)
brain_type = native_class()
records = []
all_counts = []
for condition in ['dark', 'uniform', 'left', 'right', 'disconnected']:
    start = time.perf_counter()
    brain = brain_type(GRAPH)
    stimulus = np.zeros(len(brain.retina), dtype=np.float32)
    if condition in ['uniform', 'disconnected']:
        stimulus.fill(.7)
    if condition == 'left':
        stimulus[brain.uv[:, 0] < .5] = .7
    if condition == 'right':
        stimulus[brain.uv[:, 0] >= .5] = .7
    if condition == 'disconnected':
        brain.weight.fill(0)
    combined = np.zeros(brain.n, dtype=np.int64)
    for _ in range(4):
        counts, wall = brain.step(stimulus, 50.)
        combined += counts
    direct = np.unique(np.r_[brain.retina, brain.lamina, brain.sugar])
    downstream = np.ones(brain.n, dtype=bool)
    downstream[direct] = False
    record = {'condition': condition, 'simulated_ms': 200, 'spikes': int(combined.sum()),
              'downstream_spikes': int(combined[downstream].sum()),
              'active_neurons': int(np.count_nonzero(combined)),
              'wall_seconds_including_load': time.perf_counter() - start,
              'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if sys.platform == 'darwin' else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    records.append(record)
    all_counts.append(combined)
    print(json.dumps(record), flush=True)
    if condition == 'dark':
        ids = brain.ids.copy()
        excluded = direct.copy()
    del brain
matrix = np.asarray(all_counts[:4])
variation = np.ptp(matrix, axis=0)
variation[excluded] = 0
candidates = np.flatnonzero(variation > 0)
if len(candidates) < 50:
    raise RuntimeError('Insufficient responsive downstream neurons for five readouts')
# Choose up to 500 high-response downstream neurons, without coding task outcomes.
selected = candidates[np.argsort(-variation[candidates], kind='stable')[:500]]
selected = np.random.default_rng(20260914).permutation(selected)
groups = {a: selected[i::len(ACTIONS)] for i, a in enumerate(ACTIONS)}
config = {'schema': 'flycoder.neural-map.v1', 'features': FEATURES, 'duration_ms': 100,
          'graph_sha256': digest(GRAPH), 'kernel_source_sha256': digest(UPSTREAM / 'doom/kernel.cpp'),
          'selection': 'Top 500 downstream neurons by synthetic-stimulus count range; excludes directly driven populations. Seeded partition, no coding-task outcome tuning.',
          'seed': 20260914, 'learning': False,
          'readouts': {a: {'indices': g.tolist(), 'ids': ids[g].astype(str).tolist()} for a, g in groups.items()}}
(out / 'neural-map.json').write_text(json.dumps(config, indent=2) + '\n')
(out / 'neural-probe.json').write_text(json.dumps({'conditions': records, 'responsive_candidates': len(candidates), 'readout_neurons': len(selected)}, indent=2) + '\n')
np.savez(out / 'probe-counts.npz', counts=np.asarray(all_counts), ids=ids)
assert records[-1]['downstream_spikes'] == 0, 'Disconnected control should remove downstream propagation'
assert records[1]['downstream_spikes'] > 0, 'Uniform stimulus must reach downstream neurons'
assert not np.array_equal(all_counts[2], all_counts[3]), 'Left/right stimuli should differ'
print('Calibration and causal probe complete', flush=True)
