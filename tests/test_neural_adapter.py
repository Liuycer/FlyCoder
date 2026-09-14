import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flycoder.connectome import MockConnectome, NeuralConnectome, RandomConnectome
from flycoder.controller import Controller
from flycoder.state import Action, State

try:
    import numpy as np
except ImportError:
    np = None


class NeuralContractTests(unittest.TestCase):
    def test_tied_neural_actions_rejected(self):
        class Backend:
            requires_distinct_scores = True
            def stimulate_and_step(self, features):
                return {a.value: 0.0 for a in Action}
        policy = NeuralConnectome(Backend())
        with self.assertRaisesRegex(RuntimeError, 'tied'):
            policy.select(State().encode(12, 3), [Action.READ, Action.EDIT])

    def test_seeded_random_is_reproducible(self):
        sequences = []
        for _ in range(2):
            policy = RandomConnectome()
            policy.reset(9)
            sequences.append([policy.select({}, list(Action)) for _ in range(10)])
        self.assertEqual(*sequences)

    def test_exploration_offers_choices_and_keeps_done_guard(self):
        controller = Controller(None, MockConnectome(), None, None, 'task', Path('.'), explore_actions=True)
        controller.state = State(read=True, edited=True, attempts=1, last_action='EDIT')
        self.assertEqual(controller.allowed(), [Action.READ, Action.EDIT, Action.TEST])
        self.assertNotIn(Action.DONE, controller.allowed())
        controller.state.tested = True
        controller.state.passed = True
        self.assertEqual(controller.allowed(), [Action.DONE])

    def test_final_edit_budget_still_allows_test(self):
        controller = Controller(None, MockConnectome(), None, None, 'task', Path('.'), explore_actions=True)
        controller.state = State(read=True, edited=True, attempts=3, last_action='EDIT')
        self.assertIn(Action.TEST, controller.allowed())
        self.assertNotIn(Action.EDIT, controller.allowed())

    @unittest.skipIf(np is None, 'optional neural dependencies not installed')
    def test_encoder_bounds_and_nonfinite(self):
        from flycoder.malecns import encode_stimulus
        uv = np.array([[0., 0.], [.5, 1.], [1., 1.]], dtype=np.float32)
        output = encode_stimulus({'read': 3, 'reward': -100}, uv)
        self.assertTrue(np.all((output >= .05 - 1e-6) & (output <= .95 + 1e-6)))
        with self.assertRaises(ValueError):
            encode_stimulus({'read': float('nan')}, uv)

    @unittest.skipIf(np is None, 'optional neural dependencies not installed')
    def test_mapping_hash_mismatch_stops_before_native_load(self):
        from flycoder.malecns import MaleCNSBackend, FEATURES
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / 'map.json'
            mapping.write_text(json.dumps({'schema': 'flycoder.neural-map.v1', 'features': FEATURES, 'graph_sha256': 'expected'}))
            with patch('flycoder.malecns.digest', return_value='different'):
                with self.assertRaisesRegex(ValueError, 'Graph differs'):
                    MaleCNSBackend(mapping).reset()
