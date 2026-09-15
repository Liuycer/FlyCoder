"""Tests for the external task-bench orchestrator."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from flycoder.connectome import NeuralConnectome
from flycoder.controller import Controller
from flycoder.llm import MockCodingAdapter
from flycoder.sandbox import GitSandbox
from flycoder.testing import TestRunner

from test_run_evidence import MeasuredFixture, ROOT

spec = importlib.util.spec_from_file_location('run_task_bench',
                                              ROOT / 'scripts/run_task_bench.py')
run_task_bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_task_bench)


class TaskBenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_source(self, name, buggy='return None\n', tests=None, metadata=None):
        task = self.root / 'tasks' / name
        task.mkdir(parents=True)
        (task / 'buggy.py').write_text(buggy)
        tests = tests or ('def test_one():\n    assert True\n')
        (task / 'test.py').write_text(tests)
        (task / 'task.json').write_text(json.dumps(metadata or {'id': 'x'}) + '\n')
        (task / 'fixed.py').write_text('return True\n')
        return task

    def test_task_prompt_comes_from_the_task_json(self):
        task = self.make_source('005_merge', metadata={
            'title': '字典合并', 'description': 'updates=None 时崩溃。', 'id': '005'})
        self.assertEqual(run_task_bench.task_prompt(task),
                         '字典合并: updates=None 时崩溃。')

    def test_task_prompt_refuses_a_task_without_a_description(self):
        # No description means the controller would quietly fix its built-in demo
        # function instead of the repository it was handed.
        task = self.make_source('006_blank', metadata={'title': '没有描述'})
        with self.assertRaisesRegex(ValueError, 'would fall back to'):
            run_task_bench.task_prompt(task)
        with self.assertRaisesRegex(ValueError, 'could not be read'):
            run_task_bench.task_prompt(task / 'missing')

    def test_run_one_passes_the_task_text_to_the_container(self):
        args = argparse.Namespace(llm='chat-completions', tie_extra_windows=2,
                                  max_steps=12, max_attempts=3, editable=['buggy.py'],
                                  llm_timeout=120, dry_run=True, run_timeout=60)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            outcome = run_task_bench.run_one('name', 0, self.root / 'input',
                                             '/data/runs/x', self.root / 'x.log',
                                             args, '排序: 比较符号写反了')
        self.assertEqual(outcome, {'status': 'dry_run'})
        self.assertIn('--task 排序: 比较符号写反了', output.getvalue())

    def test_dry_run_batch_derives_each_prompt_from_its_own_task_json(self):
        self.make_source('007_palindrome', buggy='def f(s):\n    return False\n',
                         tests='from buggy import f\n\n'
                               'def test_f():\n    assert f("aba") is True\n',
                         metadata={'title': '回文判断', 'description': '总是返回 False。'})
        output = io.StringIO()
        argv = ['run_task_bench', '--source', str(self.root / 'tasks'), '--output',
                str(self.root / 'out'), '--batch', 'dry', '--dry-run', '--no-build']
        with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
            code = run_task_bench.main()
        self.assertEqual(code, 0)
        printed = output.getvalue()
        self.assertIn('--task 回文判断: 总是返回 False。', printed)
        manifest = json.loads((self.root / 'out/dry/inputs/007_palindrome'
                               '/source-manifest.json').read_text())
        self.assertEqual(manifest['task_prompt'], '回文判断: 总是返回 False。')

    def test_count_and_wrapper(self):
        test_file = self.root / 'test.py'
        test_file.write_text('def test_a():\n    assert True\n\n'
                             'def helper():\n    pass\n\n'
                             'def test_b():\n    assert True\n')
        self.assertEqual(run_task_bench.count_test_functions(test_file),
                         ['test_a', 'test_b'])
        wrapper = run_task_bench.wrapper_source(2)
        self.assertIn('two unchanged', wrapper)
        self.assertIn('len(names) != 2', wrapper)

    def test_prepare_task_copies_files_and_excludes_answer(self):
        task = self.make_source('001_demo', buggy='def f():\n    return 1\n',
                                tests='def test_f():\n    assert f() == 1\n')
        (task / 'assets').mkdir()
        (task / 'assets' / 'data.txt').write_text('payload')
        destination = self.root / 'out' / '001_demo'
        manifest = run_task_bench.prepare_task(task, destination)
        self.assertEqual(manifest['test_functions'], ['test_f'])
        self.assertIn('buggy.py', manifest['sha256'])
        self.assertIn('assets/data.txt', manifest['sha256'])
        self.assertEqual(manifest['excluded'], ['fixed.py'])
        self.assertFalse((destination / 'fixed.py').exists())
        self.assertTrue((destination / 'tests/test_original.py').exists())
        self.assertEqual(manifest['sha256']['buggy.py'],
                         run_task_bench.sha256(task / 'buggy.py'))

    def test_prepare_task_rejects_tasks_without_functions(self):
        task = self.make_source('002_demo', tests='CONSTANT = 1\n')
        with self.assertRaisesRegex(ValueError, 'no top-level test_'):
            run_task_bench.prepare_task(task, self.root / 'out')

    def test_plan_runs_task_major_order_and_limit(self):
        self.assertEqual(run_task_bench.plan_runs(['a', 'b'], [0, 1]),
                         [('a', 0), ('a', 1), ('b', 0), ('b', 1)])
        self.assertEqual(run_task_bench.plan_runs(['a', 'b'], [0, 1], limit=2),
                         [('a', 0), ('a', 1)])

    def test_baseline_check_reports_untouched_test_run(self):
        task = self.make_source('003_demo', buggy='def f():\n    return 1\n',
                                tests='from buggy import f\n\n'
                                      'def test_f():\n    assert f() == 1\n')
        destination = self.root / 'input'
        run_task_bench.prepare_task(task, destination)
        result = run_task_bench.baseline_check(destination, 1)
        self.assertTrue(result['passed'])
        self.assertEqual(result['tests_run'], 1)
        with self.assertRaisesRegex(ValueError, 'ran 1 of 2'):
            run_task_bench.baseline_check(destination, 2)

    def test_baseline_check_rejects_a_task_whose_tests_hang(self):
        # 018_producer_consumer blocks forever on a full queue when its consumer
        # exits early; an unbounded pre-flight would hang the whole batch.
        import textwrap
        task = self.make_source(
            '004_hang',
            buggy='def f():\n    return 1\n',
            tests=textwrap.dedent('''
                import time

                def test_f():
                    time.sleep(30)
            '''))
        destination = self.root / 'hang-input'
        run_task_bench.prepare_task(task, destination)
        with self.assertRaisesRegex(ValueError, 'did not finish within 5s'):
            run_task_bench.baseline_check(destination, 1, timeout=5)

    def test_batch_summary_separates_policy_stops_from_errors(self):
        rows = [
            {'task': 'a', 'seed': 0, 'outcome': 'task_solved', 'actions': 4,
             'llm_calls': 2, 'llm_model': 'deepseek-v4.1-flash',
             'usage': {'input_tokens': 100, 'output_tokens': 200},
             'review_flags': ['- ℹ️ **Untested addition**: `x`']},
            {'task': 'b', 'seed': 0, 'outcome': 'tied_scores'},
            {'task': 'c', 'seed': 0, 'outcome': 'invalid_evidence'},
        ]
        summary = run_task_bench.batch_summary_markdown('batch', rows)
        self.assertIn('solved: 1 | policy stops: 1 | needs attention: 1', summary)
        self.assertIn('Model: `deepseek-v4.1-flash`', summary)
        self.assertIn('`a` seed 0: - ℹ️', summary)
        self.assertIn('| c | 0 | invalid_evidence |', summary)

    def test_batch_summary_without_a_model_omits_the_line(self):
        summary = run_task_bench.batch_summary_markdown(
            'batch', [{'task': 'a', 'seed': 0, 'outcome': 'task_solved'}])
        self.assertNotIn('Model:', summary)

    def test_resolve_model_prefers_the_run_and_labels_the_env_fallback(self):
        ledger = {'model_from_env': False}
        self.assertEqual(run_task_bench.resolve_model(
            {'llm_model': 'from-run'}, 'from-env', ledger), 'from-run')
        self.assertFalse(ledger['model_from_env'])
        self.assertEqual(run_task_bench.resolve_model(
            {'llm_model': None}, 'from-env', ledger), 'from-env')
        self.assertTrue(ledger['model_from_env'])
        self.assertIsNone(run_task_bench.resolve_model({}, None, ledger))

    def test_review_run_strict_checks_and_writes_report(self):
        path = self.root / 'run'
        box = GitSandbox(ROOT / 'flycoder/examples/buggy_repo', path / 'repo',
                         ['calculator.py'])
        box.create()
        with contextlib.redirect_stdout(io.StringIO()):
            Controller(box, NeuralConnectome(MeasuredFixture()), MockCodingAdapter(),
                       TestRunner(), 'Fix average', path, 12, 3, True).run()
        report = run_task_bench.review_run(path)
        self.assertEqual(report['outcome'], 'task_solved')
        self.assertTrue(report['backend_verified'])
        self.assertTrue((path / 'check.json').exists())
        review = (path / 'review.md').read_text()
        self.assertIn('✅ **task_solved', review)
        self.assertIn('## Review flags', review)

    def test_export_runs_uses_an_absolute_volume_source(self):
        # A relative --volume source is read by Docker as a named volume, which fails.
        captured = []

        def fake_compose(arguments, **kwargs):
            captured.append([str(part) for part in arguments])
            return type('Result', (), {'returncode': 0, 'stdout': ''})()

        original = run_task_bench.compose
        run_task_bench.compose = fake_compose
        self.addCleanup(setattr, run_task_bench, 'compose', original)
        # Reproduce the real bug: --output research/... handed Docker a relative path.
        relative = Path(os.path.relpath(self.root / 'runs' / 'task-seed0'))
        self.assertFalse(relative.is_absolute())
        run_task_bench.export_runs('/data/runs/batch/task-seed0', relative)
        volume = captured[0][captured[0].index('--volume') + 1]
        source = volume.rsplit(':/out', 1)[0]
        self.assertTrue(Path(source).is_absolute(), volume)
        self.assertEqual(source, str(relative.resolve()))

    def test_intake_rejection_is_a_row_not_a_batch_abort(self):
        # 014_rate_limiter passes untouched: its race is timing-dependent, so the
        # harness must record that instead of paying for a task with no visible bug.
        rows = [
            {'task': '008_ok', 'seed': 0, 'outcome': 'task_solved', 'actions': 4},
            {'task': '014_rate_limiter', 'seed': None, 'outcome': 'intake_rejected',
             'reason': 'the untouched copy already passes its tests; '
                       'there is no observable bug to fix'},
        ]
        summary = run_task_bench.batch_summary_markdown('batch', rows)
        self.assertIn('Runs: 1 | solved: 1 | policy stops: 0 | needs attention: 0 '
                      '| intake rejected: 1', summary)
        self.assertIn('never reached the LLM', summary)
        self.assertIn('- `014_rate_limiter`: the untouched copy already passes', summary)
        self.assertIn('| 014_rate_limiter | — | intake_rejected |', summary)


if __name__ == '__main__':
    unittest.main()
