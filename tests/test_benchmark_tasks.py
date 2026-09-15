import json
from pathlib import Path
import tempfile
import unittest
from flycoder.sandbox import GitSandbox
from flycoder.testing import TestRunner

ROOT=Path(__file__).resolve().parents[1]

class BenchmarkTaskTests(unittest.TestCase):
    def test_each_bug_and_partial_fail_but_reference_repair_passes(self):
        tasks=json.loads((ROOT/'benchmarks/tasks.json').read_text())
        tasks+=json.loads((ROOT/'benchmarks/extended-tasks.json').read_text())
        self.assertEqual(len({t['id'] for t in tasks}),7)
        with tempfile.TemporaryDirectory() as tmp:
            for task in tasks:
                with self.subTest(task=task['id']):
                    directory=ROOT/'benchmarks/tasks'/task['id']
                    box=GitSandbox(directory/'repo',Path(tmp)/task['id'],task['editable']);box.create()
                    runner=TestRunner()
                    self.assertFalse(runner.run(box.root).passed)
                    partial = ({file:(directory/'partial'/file).read_text() for file in task['editable']}
                               if task.get('candidate_layout') == 'directory'
                               else {'module.py':(directory/'partial.py').read_text()})
                    box.apply(partial)
                    self.assertFalse(runner.run(box.root).passed)
                    solution = ({file:(directory/'solution'/file).read_text() for file in task['editable']}
                                if task.get('candidate_layout') == 'directory'
                                else {'module.py':(directory/'solution.py').read_text()})
                    box.apply(solution)
                    result=runner.run(box.root)
                    self.assertTrue(result.passed,result.output)
                    self.assertGreaterEqual(result.tests_run,3)
