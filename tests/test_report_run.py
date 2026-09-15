"""Tests for the human-readable run report generator."""
import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from report_run import generate_report


def make_run(root, summary_extra=None, events=None, patch='', check=None,
             repo_files=None):
    run_dir = root / 'run'
    run_dir.mkdir(parents=True)
    summary = {
        'schema': 'flycoder.run.v2', 'status': 'done',
        'reason': 'Current snapshot passed', 'policy': 'NeuralConnectome',
        'coder': 'MockCodingAdapter', 'llm_calls': 0, 'llm_http_attempts': 0,
        'llm_usage': [],
        'last_neural_trace': None, 'last_neural_decision': None,
    }
    if summary_extra:
        summary.update(summary_extra)
    (run_dir / 'summary.json').write_text(json.dumps(summary))
    base_events = [
        {'schema': 'flycoder.run.v2', 'event_index': 1, 'event': 'baseline',
         'passed': False, 'tests_run': 6, 'tests_skipped': 0,
         'output': 'FAIL: test_a\nFAIL: test_b\n'},
        {'schema': 'flycoder.run.v2', 'event_index': 2, 'event': 'action',
         'action': 'READ', 'state': {'attempts': 0}, 'detail': {}},
        {'schema': 'flycoder.run.v2', 'event_index': 3, 'event': 'action',
         'action': 'EDIT', 'state': {'attempts': 1}, 'detail': {}},
        {'schema': 'flycoder.run.v2', 'event_index': 4, 'event': 'action',
         'action': 'TEST', 'state': {'attempts': 1},
         'detail': {'passed': True, 'tests_run': 6, 'tests_skipped': 0, 'timed_out': False}},
        {'schema': 'flycoder.run.v2', 'event_index': 5, 'event': 'action',
         'action': 'DONE', 'state': {'attempts': 1}, 'detail': {}},
    ]
    all_events = base_events if events is None else events
    (run_dir / 'events.jsonl').write_text(
        '\n'.join(json.dumps(e) for e in all_events) + '\n')
    (run_dir / 'changes.patch').write_text(patch)
    for name, content in (repo_files or {}).items():
        path = run_dir / 'repo' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    check_path = None
    if check:
        check_path = root / 'check.json'
        check_path.write_text(json.dumps(check))
    return run_dir, check_path


SCOPE_PATCH = '''diff --git a/buggy.py b/buggy.py
--- a/buggy.py
+++ b/buggy.py
@@ -1,2 +1,4 @@
-def parse_json(text):
-    return json.loads(text)
+def parse_json(s):
+    try:
+        return json.loads(s)
+    except ValueError:
+        return None
+
+def average(values):
+    return sum(values) / len(values)
'''

BODY_ONLY_PATCH = '''diff --git a/buggy.py b/buggy.py
--- a/buggy.py
+++ b/buggy.py
@@ -1,2 +1,3 @@
 def parse_json(text):
-    return json.loads(text)
+    try:
+        return json.loads(text)
+    except ValueError:
+        return None
'''

TEST_EDIT_PATCH = '''diff --git a/tests/test_original.py b/tests/test_original.py
--- a/tests/test_original.py
+++ b/tests/test_original.py
@@ -1,2 +1,2 @@
-def test_parse_empty_string():
+def test_parse_empty_string():
+    assert True
'''

TEST_SOURCE = '''import unittest
from buggy import parse_json


class JsonTests(unittest.TestCase):
    def test_parse_empty_string(self):
        self.assertIsNone(parse_json(""))

    def test_parse_valid(self):
        self.assertEqual(parse_json('{"a": 1}'), {"a": 1})
'''


class ReportRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_task_solved_report(self):
        patch = '--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n'
        check = {'backend_verified': True, 'task_solved': True, 'outcome': 'task_solved'}
        run_dir, check_path = make_run(self.root, patch=patch, check=check)
        report = generate_report(run_dir, check_path)
        self.assertIn('✅ **task_solved', report)
        self.assertIn('```diff', report)
        self.assertIn('-old', report)
        self.assertIn('+new', report)
        self.assertIn('Mock adapter', report)
        self.assertIn('FAIL: test_a', report)

    def test_tied_scores_verdict(self):
        check = {'backend_verified': True, 'task_solved': False, 'outcome': 'tied_scores'}
        run_dir, check_path = make_run(self.root, check=check)
        report = generate_report(run_dir, check_path)
        self.assertIn('⚠️ **tied_scores', report)
        self.assertIn('policy stopped without solving', report)

    def test_llm_usage_displayed(self):
        extra = {
            'coder': 'ChatCompletionsCodingAdapter',
            'llm_model': 'deepseek-v4.1-flash',
            'llm_calls': 2, 'llm_http_attempts': 3,
            'llm_usage': [
                {'input_tokens': 1200, 'output_tokens': 300},
                {'input_tokens': 2400, 'output_tokens': 700},
            ],
        }
        run_dir, _ = make_run(self.root, summary_extra=extra)
        report = generate_report(run_dir)
        self.assertIn('Model: `deepseek-v4.1-flash`', report)
        self.assertIn('Calls: 2 | HTTP attempts: 3 (retries: 1)', report)
        self.assertIn('input 3,600 / output 1,000', report)
        self.assertIn('request 1: in 1,200, out 300', report)

    def test_llm_usage_without_a_recorded_model(self):
        extra = {
            'coder': 'ChatCompletionsCodingAdapter',
            'llm_calls': 1, 'llm_http_attempts': 1,
            'llm_usage': [{'input_tokens': 10, 'output_tokens': 20}],
        }
        run_dir, _ = make_run(self.root, summary_extra=extra)
        report = generate_report(run_dir)
        self.assertNotIn('Model:', report)
        self.assertIn('Calls: 1 | HTTP attempts: 1', report)

    def test_neural_backend_displayed(self):
        trace = {'windows': [{
            'backend': 'MaleCNS/DOOMFLY fixed-weight NativeBrain',
            'neurons': 166700, 'edges': 25582938,
            'graph_sha256': 'a' * 64, 'mapping_sha256': 'b' * 64,
            'provenance': {'machine': 'x86_64'},
        }]}
        run_dir, _ = make_run(self.root, summary_extra={'last_neural_trace': trace})
        report = generate_report(run_dir)
        self.assertIn('MaleCNS/DOOMFLY fixed-weight NativeBrain', report)
        self.assertIn('166,700 neurons', report)
        self.assertIn('`aaaaaaaaaaaa…`', report)

    def test_no_diff_shows_placeholder(self):
        run_dir, _ = make_run(self.root, patch='')
        report = generate_report(run_dir)
        self.assertIn('_No changes._', report)

    def test_flags_scope_and_compatibility(self):
        run_dir, _ = make_run(self.root, patch=SCOPE_PATCH,
                              repo_files={'test_buggy.py': TEST_SOURCE})
        report = generate_report(run_dir)
        self.assertIn('**buggy.py** −2 / +7', report)
        self.assertIn('**Untested addition**: `average`', report)
        self.assertIn('**Signature changed**: `parse_json(text)` → `parse_json(s)`',
                      report)
        self.assertIn('1 worth blocking a merge', report)

    def test_flags_test_file_edit(self):
        run_dir, _ = make_run(self.root, patch=TEST_EDIT_PATCH,
                              repo_files={'tests/test_original.py': TEST_SOURCE})
        report = generate_report(run_dir)
        self.assertIn('**Test file edited**: `tests/test_original.py`', report)
        self.assertIn('were not weakened', report)

    def test_clean_patch_has_no_flags(self):
        run_dir, _ = make_run(self.root, patch=BODY_ONLY_PATCH,
                              repo_files={'test_buggy.py': TEST_SOURCE})
        report = generate_report(run_dir)
        self.assertIn('_None: no test file was edited', report)
        self.assertNotIn('review flag(s)', report)

    def test_missing_repo_snapshot_reports_info_flag(self):
        run_dir, _ = make_run(self.root, patch=SCOPE_PATCH)
        report = generate_report(run_dir)
        self.assertIn('no test snapshot available', report)


if __name__ == '__main__':
    unittest.main()
