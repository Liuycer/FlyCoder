import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import flycoder
from flycoder.connectome import MockConnectome, NeuralConnectome
from flycoder.controller import Controller
from flycoder.llm import MockCodingAdapter, OpenAICodingAdapter
from flycoder.sandbox import GitSandbox
from flycoder.state import Action, State
from flycoder.testing import TestRunner


EXAMPLE = Path(flycoder.__file__).resolve().parent / "examples" / "buggy_repo"


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name) / "run"
        self.box = GitSandbox(EXAMPLE, self.run_dir / "repo", ["calculator.py"])
        self.box.create()

    def run_flow(self, coder=None, policy=None, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return Controller(self.box, policy or MockConnectome(), coder or MockCodingAdapter(),
                              TestRunner(), "Fix average", self.run_dir, **kwargs).run()

    def events(self):
        return [json.loads(line) for line in (self.run_dir / "events.jsonl").read_text().splitlines()]

    def test_retry_and_done_original_unchanged(self):
        before = (EXAMPLE / "calculator.py").read_bytes()
        result = self.run_flow()
        self.assertEqual(result["status"], "done")
        events = self.events()
        self.assertFalse(events[0]["passed"])
        self.assertEqual([e["action"] for e in events[1:]],
                         ["READ", "EDIT", "TEST", "RETRY", "EDIT", "TEST", "DONE"])
        tests = [e["detail"] for e in events if e.get("action") == "TEST"]
        self.assertEqual([e["passed"] for e in tests], [False, True])
        self.assertEqual(tests[-1]["tests_run"], 5)
        self.assertEqual(before, (EXAMPLE / "calculator.py").read_bytes())
        self.assertIn("raise ValueError", (self.run_dir / "changes.patch").read_text())

    def test_direct_success(self):
        result = self.run_flow(coder=MockCodingAdapter(False))
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["state"]["retries"], 0)

    def test_attempt_exhaustion_is_not_done(self):
        result = self.run_flow(max_attempts=1)
        self.assertEqual(result["status"], "exhausted")
        self.assertFalse(result["state"]["passed"])

    def test_mock_run_records_zero_llm_usage(self):
        result = self.run_flow(coder=MockCodingAdapter(False))
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["llm_calls"], 0)
        self.assertEqual(result["llm_http_attempts"], 0)
        self.assertEqual(result["llm_usage"], [])

    def test_step_exhaustion(self):
        self.assertEqual(self.run_flow(max_steps=1)["status"], "exhausted")

    def test_illegal_done_rejected(self):
        class BadPolicy(MockConnectome):
            def select(self, observation, allowed):
                return Action.DONE
        self.assertEqual(self.run_flow(policy=BadPolicy())["status"], "error")

    def test_stale_success_rejected(self):
        box = self.box
        class MutatingPolicy(MockConnectome):
            def select(self, observation, allowed):
                if Action.DONE in allowed:
                    box.apply({"calculator.py": "# changed after testing\n"})
                return super().select(observation, allowed)
        self.assertEqual(self.run_flow(policy=MutatingPolicy())["status"], "error")

    def test_protected_test_and_path_escape(self):
        for name in ["../outside.py", "/tmp/outside.py", "tests/test_calculator.py", ".git/config"]:
            with self.assertRaises(ValueError):
                self.box.apply({name: "bad"})

    def test_batch_validation_does_not_partially_write(self):
        before = (self.box.root / "calculator.py").read_text()
        with self.assertRaises(ValueError):
            self.box.apply({"calculator.py": "bad", "../outside": "bad"})
        self.assertEqual(before, (self.box.root / "calculator.py").read_text())

    def test_symlink_edit_rejected(self):
        p = self.box.root / "calculator.py"
        p.unlink()
        p.symlink_to(EXAMPLE / "calculator.py")
        with self.assertRaises(ValueError):
            self.box.apply({"calculator.py": "bad"})

    def test_llm_usage_extracted_from_completed_run(self):
        class MeteredCoder(MockCodingAdapter):
            def __init__(self):
                super().__init__(False)
                self.http_attempts = 2
                self.usage_records = [
                    {"input_tokens": 123, "output_tokens": 45},
                    {"input_tokens": 234, "output_tokens": 67},
                ]

        result = self.run_flow(coder=MeteredCoder())
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["llm_calls"], 2)
        self.assertEqual(result["llm_http_attempts"], 2)
        self.assertEqual(result["llm_usage"],
                         [{"input_tokens": 123, "output_tokens": 45},
                          {"input_tokens": 234, "output_tokens": 67}])

    def test_llm_usage_handles_partial_token_fields(self):
        class PartialCoder(MockCodingAdapter):
            def __init__(self):
                super().__init__(False)
                self.http_attempts = 3
                self.usage_records = [
                    {"input_tokens": 100},
                    {"output_tokens": 50},
                    {},
                ]

        result = self.run_flow(coder=PartialCoder())
        self.assertEqual(result["llm_calls"], 3)
        self.assertEqual(result["llm_http_attempts"], 3)
        self.assertEqual(result["llm_usage"],
                         [{"input_tokens": 100},
                          {"output_tokens": 50},
                          {}])

    def test_summary_records_the_model_that_produced_the_run(self):
        class NamedCoder(MockCodingAdapter):
            def __init__(self):
                super().__init__(False)
                self.model = "deepseek-v4.1-flash"

        result = self.run_flow(coder=NamedCoder())
        self.assertEqual(result["llm_model"], "deepseek-v4.1-flash")

    def test_summary_omits_a_model_the_coder_does_not_report(self):
        result = self.run_flow(coder=MockCodingAdapter(False))
        self.assertIsNone(result["llm_model"])


class RunnerTests(unittest.TestCase):
    def run_repo(self, code, timeout=3):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "tests" / "test_case.py").write_text(code)
            return TestRunner(timeout).run(root)

    def test_zero_tests_is_failure(self):
        result = self.run_repo("# no tests\n")
        self.assertFalse(result.passed)
        self.assertEqual(result.tests_run, 0)

    def test_timeout(self):
        result = self.run_repo("import time\ntime.sleep(30)\n", timeout=0.2)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.passed)

    def test_all_skipped_is_not_success(self):
        result = self.run_repo("import unittest\n@unittest.skip('not implemented')\n"
                               "class T(unittest.TestCase):\n def test_skip(self): pass\n")
        self.assertEqual(result.tests_run, 1)
        self.assertFalse(result.passed)

    def test_large_output_bounded(self):
        result = self.run_repo("print('x' * 100000)\n")
        self.assertLessEqual(len(result.output), 32768)

    def test_no_api_key_in_child(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-secret"}):
            result = self.run_repo("import os, unittest\nclass T(unittest.TestCase):\n"
                                   " def test_env(self):\n  self.assertNotIn('OPENAI_API_KEY', os.environ)\n")
        self.assertTrue(result.passed)


class AdapterTests(unittest.TestCase):
    def test_state_normalization(self):
        f = State(step=100, attempts=50, changed_files=99).encode(12, 3)["features"]
        self.assertEqual(f["step_fraction"], 1.0)
        self.assertEqual(f["attempt_fraction"], 1.0)
        self.assertTrue(all(isinstance(v, float) for v in f.values()))

    def test_neural_scores_mask_and_nan(self):
        class Backend:
            def stimulate_and_step(self, features):
                return {"READ": 0.2, "DONE": 1000}
        policy = NeuralConnectome(Backend())
        self.assertEqual(policy.select(State().encode(12, 3), [Action.READ]), Action.READ)
        with self.assertRaises(ValueError):
            policy.select(State().encode(12, 3), [Action.EDIT])
        with patch.object(policy.backend, "stimulate_and_step", return_value={"READ": float("nan")}):
            with self.assertRaises(ValueError):
                policy.select(State().encode(12, 3), [Action.READ])

    def test_openai_response_contract_offline(self):
        body = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"analysis": "fix", "files": {"calculator.py": "fixed"}})}]}]}
        response = io.BytesIO(json.dumps(body).encode())
        with patch("urllib.request.urlopen", return_value=response) as call:
            result = OpenAICodingAdapter("configured-model", "fake-key").edit("task", {}, ["calculator.py"], "", "", 1)
        self.assertEqual(result, {"calculator.py": "fixed"})
        request = json.loads(call.call_args[0][0].data)
        self.assertFalse(request["store"])
        self.assertEqual(request["text"]["format"]["type"], "json_object")

    def test_openai_incomplete_rejected(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"status":"incomplete"}')):
            with self.assertRaises(RuntimeError):
                OpenAICodingAdapter("configured-model", "fake-key").read("task", {})

if __name__ == "__main__":
    unittest.main()
