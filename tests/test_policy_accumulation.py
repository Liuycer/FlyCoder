from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from flycoder.connectome import NeuralConnectome, NeuralSelectionError
from flycoder.controller import Controller
from flycoder.llm import MockCodingAdapter
from flycoder.sandbox import GitSandbox
from flycoder.state import Action, State
from flycoder.testing import TestRunner
from test_run_evidence import MeasuredFixture, checker, ROOT


class SequenceBackend(MeasuredFixture):
    def __init__(self, sequence):
        super().__init__()
        self.sequence = sequence
    def stimulate_and_step(self, features):
        super().stimulate_and_step(features)
        rates = {a: float(self.sequence[min(self.calls-1,len(self.sequence)-1)].get(a,0)) for a in checker.NAMES}
        self.last_trace['scores_hz'] = rates
        self.last_trace['readout_spikes'] = {a:int(v*10) for a,v in rates.items()}
        return rates


class AccumulationTests(unittest.TestCase):
    def test_default_stops_but_accumulation_resolves_using_counts(self):
        seq=[{'READ':20,'TEST':20},{'READ':0,'TEST':40}]
        obs=State(read=True,edited=True).encode(12,3)
        default=NeuralConnectome(SequenceBackend(seq)); default.reset()
        with self.assertRaises(NeuralSelectionError): default.select(obs,[Action.READ,Action.TEST])
        policy=NeuralConnectome(SequenceBackend(seq),2);policy.reset()
        self.assertEqual(policy.select(obs,[Action.READ,Action.TEST]),Action.TEST)
        self.assertEqual(policy.last_trace['scores_hz']['TEST'],30)
        self.assertEqual(len(policy.last_trace['windows']),2)
        self.assertEqual(policy.last_trace['simulated_ms'],200)

    def test_persistent_tie_stops_at_budget_without_fallback(self):
        policy=NeuralConnectome(SequenceBackend([{'READ':20,'TEST':20}]),2);policy.reset()
        with self.assertRaises(NeuralSelectionError): policy.select(State().encode(12,3),[Action.READ,Action.TEST])
        self.assertEqual(policy.backend.calls,3)
        self.assertIsNone(policy.last_decision['selected_action'])

    def test_unique_maximum_does_not_spend_extra_windows(self):
        policy=NeuralConnectome(SequenceBackend([{'READ':30,'TEST':20}]),2);policy.reset()
        self.assertEqual(policy.select(State().encode(12,3),[Action.READ,Action.TEST]),Action.READ)
        self.assertEqual(policy.backend.calls,1)

    def test_real_test_chain_and_tampered_window_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'run';box=GitSandbox(ROOT/'flycoder/examples/buggy_repo',run/'repo',['calculator.py']);box.create()
            with contextlib.redirect_stdout(io.StringIO()):
                Controller(box,NeuralConnectome(MeasuredFixture('tie'),2),MockCodingAdapter(False),TestRunner(),'Fix average',run,12,3,True).run()
            self.assertTrue(checker.validate_run(run/'summary.json')['task_solved'])
            events=[json.loads(x) for x in (run/'events.jsonl').read_text().splitlines()]
            self.assertEqual(len(events[3]['neural_trace']['windows']),2)
            for kind in ['score','stimulus','call','extra']:
                broken=deepcopy(events);trace=broken[3]['neural_trace']
                if kind=='score':trace['scores_hz']['TEST']+=1
                if kind=='stimulus':trace['windows'][1]['stimulus_sha256']='d'*64
                if kind=='call':trace['windows'][1]['call']+=1
                if kind=='extra':trace['windows'].append(deepcopy(trace['windows'][-1]))
                (run/'events.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in broken))
                with self.assertRaises(checker.EvidenceError):checker.validate_run(run/'summary.json')

    def test_silence_still_stops_without_extra_sampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'run';box=GitSandbox(ROOT/'flycoder/examples/buggy_repo',run/'repo',['calculator.py']);box.create()
            with contextlib.redirect_stdout(io.StringIO()):
                Controller(box,NeuralConnectome(MeasuredFixture('silent'),2),MockCodingAdapter(False),TestRunner(),'Fix average',run,12,3,True).run()
            self.assertEqual(checker.validate_run(run/'summary.json')['outcome'],'silent_readouts')


if __name__=='__main__':unittest.main()
