from copy import deepcopy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flycoder.connectome import NeuralConnectome, NeuralSelectionError
from flycoder.controller import Controller
from flycoder.llm import MockCodingAdapter
from flycoder.sandbox import GitSandbox
from flycoder.testing import TestRunner

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('run_evidence', ROOT / 'scripts/check_neural_run.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class MeasuredFixture:
    """Synthetic trace fixture for log validation, not a real-connectome claim."""
    requires_distinct_scores = True
    def __init__(self, fail=None):
        self.fail = fail
    def reset(self, seed=0):
        self.calls = 0
        self.last_trace = None
    def stimulate_and_step(self, f):
        self.calls += 1
        target = ('READ' if not f['read'] else 'DONE' if f['passed'] else
                  'RETRY' if f['tested'] else 'EDIT' if not f['edited'] else 'TEST')
        rates = {a: 50. if a == target else 10. for a in checker.NAMES}
        if self.calls == 3 and self.fail == 'tie':
            rates['READ'] = rates['TEST'] = 50.
        if self.calls == 3 and self.fail == 'silent':
            rates = {a: 0. for a in checker.NAMES}
        if self.calls == 3 and self.fail == 'backend':
            raise RuntimeError('Legal neural action scores are tied; no rule fallback')
        self.last_trace = {
            'backend': 'MaleCNS/DOOMFLY fixed-weight NativeBrain', 'control': 'intact',
            'call': self.calls, 'neurons': 166700, 'edges': 25582938,
            'simulated_ms': 100., 'cumulative_simulated_ms': self.calls * 100.,
            'total_spikes': int(sum(rates.values()) * 10),
            'scores_hz': rates, 'weight_learning': False,
            **{k: 'a' * 64 for k in ['spikes_sha256', 'graph_sha256', 'mapping_sha256', 'stimulus_sha256']},
            'readout_spikes': {a: int(v * 10) for a, v in rates.items()},
            'provenance': {'platform': 'test', 'machine': 'fixture', 'python': 'test', 'numpy': 'test',
                           'kernel_source_sha256': 'b' * 64, 'kernel_binary_sha256': 'c' * 64,
                           'readout_sizes': {a: 100 for a in checker.NAMES}},
        }
        if self.calls == 3 and self.fail == 'silent':
            raise NeuralSelectionError('silent_readouts', 'Neural readouts are silent; no mock fallback')
        return rates
    def reward(self, value):
        pass
    def close(self):
        pass


class RunEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'run'

    def run_fixture(self, fail=None, max_steps=12, max_attempts=3, fail_first=False):
        box = GitSandbox(ROOT / 'flycoder/examples/buggy_repo', self.path / 'repo', ['calculator.py'])
        box.create()
        with contextlib.redirect_stdout(io.StringIO()):
            Controller(box, NeuralConnectome(MeasuredFixture(fail)), MockCodingAdapter(fail_first),
                       TestRunner(), 'Fix average', self.path, max_steps, max_attempts, True).run()
        self.summary = json.loads((self.path / 'summary.json').read_text())
        self.events = [json.loads(line) for line in (self.path / 'events.jsonl').read_text().splitlines()]

    def save(self):
        (self.path / 'summary.json').write_text(json.dumps(self.summary))
        (self.path / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in self.events))

    def verify(self):
        self.save()
        return checker.validate_run(self.path / 'summary.json')

    def test_real_test_chain_is_required_for_success(self):
        self.run_fixture()
        self.assertTrue(self.verify()['task_solved'])
        self.events = self.events[:2]  # Baseline + READ, but malicious summary says done.
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_missing_done_is_not_success(self):
        self.run_fixture()
        self.events.pop()
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_passing_flag_cannot_override_failed_zero_skipped_or_timed_out_tests(self):
        self.run_fixture()
        original = deepcopy(self.events)
        for changes in [{'returncode': 1}, {'tests_run': 0}, {'tests_skipped': 5}, {'timed_out': True}, {'output': 'no tests'}, {'tests_skipped': 0, 'output': 'Ran 5 tests in 0.1s\n\nOK (skipped=5)\n'}]:
            with self.subTest(changes=changes):
                self.events = deepcopy(original)
                test = next(e for e in self.events if e.get('action') == 'TEST')
                test['detail'].update(changes)
                with self.assertRaises(checker.EvidenceError):
                    self.verify()

    def test_post_test_edit_or_fingerprint_change_rejected(self):
        self.run_fixture()
        original = deepcopy(self.events)
        self.events[-1]['repo_fingerprint'] = 'd' * 64
        with self.assertRaises(checker.EvidenceError):
            self.verify()
        self.events = deepcopy(original)
        self.events[-1]['action'] = 'EDIT'
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_summary_disagreement_rejected(self):
        self.run_fixture()
        original = deepcopy(self.summary)
        for field, value in [('policy', 'MockConnectome'), ('repo_fingerprint', 'd' * 64), ('tested_fingerprint', None)]:
            self.summary = deepcopy(original)
            self.summary[field] = value
            with self.subTest(field=field), self.assertRaises(checker.EvidenceError):
                self.verify()
        self.summary = deepcopy(original)
        self.summary['state']['passed'] = False
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_tie_logs_current_attempt_instead_of_previous_action(self):
        self.run_fixture('tie')
        error = self.events[-1]
        self.assertEqual(error['phase'], 'select')
        self.assertEqual(error['state']['step'], 3)
        self.assertEqual(error['allowed'], ['READ', 'EDIT', 'TEST'])
        self.assertEqual(error['neural_trace']['call'], 3)
        self.assertNotIn('selected_action', error['neural_trace'])
        self.assertEqual(error['neural_decision']['tied_actions'], ['READ', 'TEST'])
        self.assertEqual(error['neural_decision']['top_margin_hz'], 0.)
        self.assertIsNone(error['neural_decision']['selected_action'])
        report = self.verify()
        self.assertTrue(report['backend_verified'])
        self.assertFalse(report['task_solved'])
        self.assertEqual(report['outcome'], 'tied_scores')

    def test_tie_without_evidence_or_with_stale_trace_is_rejected(self):
        self.run_fixture('tie')
        original = deepcopy(self.events)
        self.events[-1]['neural_trace'] = self.events[-2]['neural_trace']
        with self.assertRaises(checker.EvidenceError):
            self.verify()
        self.events = deepcopy(original)
        self.events[-1]['neural_decision']['tied_actions'] = []
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_reason_string_alone_does_not_pass_as_policy_outcome(self):
        self.run_fixture('backend')
        self.assertEqual(self.events[-1]['neural_decision']['reason'], 'backend_error')
        self.assertIsNone(self.events[-1]['neural_trace'])
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_silence_records_current_zero_scores(self):
        self.run_fixture('silent')
        self.assertEqual(self.events[-1]['neural_trace']['call'], 3)
        self.assertTrue(all(v == 0 for v in self.events[-1]['neural_trace']['scores_hz'].values()))
        self.assertEqual(self.verify()['outcome'], 'silent_readouts')

    def test_step_budget_has_to_be_exhausted(self):
        self.run_fixture(max_steps=1)
        self.assertEqual(self.verify()['outcome'], 'budget_exhausted')
        self.summary['max_steps'] = 12
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_edit_budget_exhaustion_is_not_success(self):
        self.run_fixture(max_attempts=1, fail_first=True)
        self.assertEqual(self.verify()['outcome'], 'budget_exhausted')

    def test_nonfinite_time_boolean_score_and_changed_graph_rejected(self):
        self.run_fixture()
        original = deepcopy(self.events)
        for field, value in [('simulated_ms', float('inf')), ('graph_sha256', 'd' * 64)]:
            self.events = deepcopy(original)
            self.events[2]['neural_trace'][field] = value
            with self.subTest(field=field), self.assertRaises(checker.EvidenceError):
                self.verify()
        self.events = deepcopy(original)
        self.events[2]['neural_trace']['scores_hz']['READ'] = True
        with self.assertRaises(checker.EvidenceError):
            self.verify()

    def test_require_done_fails_for_verified_policy_exit(self):
        self.run_fixture('tie')
        with patch('sys.argv', ['checker', '--summary', str(self.path / 'summary.json'), '--require-done']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(checker.main(), 1)

    def test_legacy_runs_fail_closed(self):
        self.run_fixture()
        self.summary.pop('schema')
        with self.assertRaisesRegex(checker.EvidenceError, 'v2 evidence'):
            self.verify()


class MalformedEvidenceTests(unittest.TestCase):
    def test_malformed_event_produces_failed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            from flycoder.state import State
            summary = {'schema': checker.SCHEMA, 'policy': 'NeuralConnectome', 'state': State().snapshot(),
                       'max_steps': 12, 'max_attempts': 3, 'explore_actions': True, 'seed': 0}
            (root / 'summary.json').write_text(json.dumps(summary))
            (root / 'events.jsonl').write_text('123\n')
            with patch('sys.argv', ['checker', '--summary', str(root / 'summary.json'), '--report', str(root / 'report.json')]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(checker.main(), 1)
            self.assertEqual(json.loads((root / 'report.json').read_text())['outcome'], 'invalid_evidence')
