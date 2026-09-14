"""MaleCNS fixed-weight neural backend. Engineered stimulus/readout, no learning."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from .connectome import NeuralBackend

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'vendor/doomfly'
GRAPH = UPSTREAM / 'outputs/doom/malecns_v1/graph.npz'
FEATURES = ['read', 'edited', 'tested', 'passed', 'timed_out', 'step_fraction',
            'attempt_fraction', 'change_fraction', 'reward', 'last_READ',
            'last_EDIT', 'last_TEST', 'last_RETRY', 'last_DONE']
ACTIONS = ['READ', 'EDIT', 'TEST', 'RETRY', 'DONE']


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def native_class():
    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))
    try:
        from doom.native import NativeBrain
    except ImportError as exc:
        raise RuntimeError('Use .venv-neural/bin/python after neural environment setup') from exc
    return NativeBrain


def encode_stimulus(features, uv):
    import numpy as np
    values = []
    for key in FEATURES:
        value = float(features.get(key, 0.0))
        if not np.isfinite(value):
            raise ValueError('Nonfinite neural feature: ' + key)
        values.append(np.clip((value + 1) / 2 if key == 'reward' else value, 0, 1))
    bands = np.minimum((uv[:, 0] * len(FEATURES)).astype(int), len(FEATURES) - 1)
    # State feature order maps to fixed retinal bands, not to desired actions.
    return np.asarray(0.05 + 0.90 * np.asarray(values)[bands], dtype=np.float32)


class MaleCNSBackend(NeuralBackend):
    requires_distinct_scores = True
    def __init__(self, mapping=None, control='intact'):
        self.mapping_path = Path(mapping or os.getenv('NEURAL_MAPPING') or ROOT / 'research/neural-map.json')
        if control not in {'intact', 'no-stimulus', 'disconnected', 'shuffled-readout'}:
            raise ValueError('Unknown neural control')
        self.control = control
        self.brain = None
        self.last_trace = {}

    def reset(self, seed=0):
        import numpy as np
        self.config = json.loads(self.mapping_path.read_text())
        if self.config['schema'] != 'flycoder.neural-map.v1' or self.config['features'] != FEATURES:
            raise ValueError('Neural mapping schema mismatch')
        if digest(GRAPH) != self.config['graph_sha256']:
            raise ValueError('Graph differs from calibrated mapping')
        if digest(UPSTREAM / 'doom/kernel.cpp') != self.config['kernel_source_sha256']:
            raise ValueError('Kernel differs from calibrated mapping')
        self.brain = native_class()(GRAPH)
        self.groups = {a: np.asarray(self.config['readouts'][a]['indices'], dtype=int) for a in ACTIONS}
        for action, indices in self.groups.items():
            if not len(indices) or np.any(indices < 0) or np.any(indices >= self.brain.n):
                raise ValueError('Invalid neural readout indices')
            if self.brain.ids[indices].astype(str).tolist() != self.config['readouts'][action]['ids']:
                raise ValueError('Neuron ID mapping mismatch')
        if self.control == 'disconnected':
            self.brain.weight.fill(0)  # Explicit causal control; never used as intact backend.
        if self.control == 'shuffled-readout':
            names = np.random.default_rng(seed + 100).permutation(ACTIONS).tolist()
            self.groups = {a: self.groups[b] for a, b in zip(ACTIONS, names)}
        self.last_reward = 0.0
        self.last_trace = {}
        self.calls = 0
        self.duration_ms = float(self.config['duration_ms'])
        if not np.isfinite(self.duration_ms) or not 0 < self.duration_ms <= 1000:
            raise ValueError('Invalid neural simulation duration')

    def stimulate_and_step(self, features):
        import numpy as np
        stimulus = encode_stimulus(features, self.brain.uv)
        if self.control == 'no-stimulus':
            stimulus.fill(0)
        start = time.perf_counter()
        counts, kernel_seconds = self.brain.step(stimulus, self.duration_ms)
        rates = {a: float(counts[g].mean() * 1000 / self.duration_ms) for a, g in self.groups.items()}
        if self.control == 'intact' and not any(v > 0 for v in rates.values()):
            raise RuntimeError('Neural readouts are silent; no mock fallback')
        self.calls += 1
        self.last_trace = {'backend': 'MaleCNS/DOOMFLY fixed-weight NativeBrain',
            'control': self.control, 'call': self.calls, 'neurons': self.brain.n,
            'edges': len(self.brain.post), 'simulated_ms': self.duration_ms,
            'cumulative_simulated_ms': self.brain.sim_ms, 'kernel_seconds': kernel_seconds,
            'wall_seconds': time.perf_counter() - start, 'total_spikes': int(counts.sum()),
            'active_neurons': int(np.count_nonzero(counts)), 'scores_hz': rates,
            'stimulus_sha256': hashlib.sha256(stimulus.tobytes()).hexdigest(),
            'spikes_sha256': hashlib.sha256(counts.tobytes()).hexdigest(),
            'graph_sha256': self.config['graph_sha256'], 'mapping_sha256': digest(self.mapping_path),
            'weight_learning': False, 'feedback_reward': self.last_reward}
        return rates

    def reward(self, value):
        self.last_reward = float(value)  # Logged only; weights remain fixed.

    def close(self):
        self.brain = None
