import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'package_neural_docker_evidence',
    ROOT / 'scripts/package_neural_docker_evidence.py',
)
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class NeuralDockerEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_dir = self.root / 'run'
        self.run_dir.mkdir()
        (self.run_dir / 'summary.json').write_text('{"status": "done"}\n')
        (self.run_dir / 'events.jsonl').write_text('{"event": "baseline"}\n')
        self.report = self.root / 'check.json'
        self.report.write_text(json.dumps({
            'backend_verified': True,
            'task_solved': True,
            'outcome': 'task_solved',
            'completed_actions': 8,
        }))
        self.demo_log = self.root / 'demo.log'
        self.demo_log.write_text('DONE\n')

    def package(self, archive=None, require_done=True):
        argv = [
            '--run-dir', str(self.run_dir),
            '--check-report', str(self.report),
            '--demo-log', str(self.demo_log),
            '--commit', 'a' * 40,
            '--created-utc', '2026-09-15T00:00:00Z',
            '--output', str(self.root / 'manifest.json'),
        ]
        if require_done:
            argv.append('--require-done')
        if archive is not None:
            argv.extend(['--archive', str(archive)])
        argv.extend(['--accepted-outcomes', getattr(self, 'accepted_outcomes', 'task_solved')])
        result = packager.main(argv)
        if result != 0:
            return result
        return json.loads((self.root / 'manifest.json').read_text())

    def test_manifest_hashes_all_evidence(self):
        manifest = self.package()
        paths = {record['path']: record for record in manifest['files']}
        self.assertIn('run/summary.json', paths)
        self.assertIn('run/events.jsonl', paths)
        self.assertIn('container/demo.log', paths)
        self.assertEqual(paths['run/summary.json']['sha256'],
                         hashlib.sha256((self.run_dir / 'summary.json').read_bytes()).hexdigest())
        self.assertTrue(manifest['check']['backend_verified'])

    def test_require_done_rejects_policy_exit(self):
        self.report.write_text(json.dumps({
            'backend_verified': True,
            'task_solved': False,
            'outcome': 'tied_scores',
        }))
        self.accepted_outcomes = 'task_solved,tied_scores'
        self.assertEqual(self.package(), 2)

    def test_policy_exit_can_be_recorded_without_task_success_claim(self):
        self.report.write_text(json.dumps({
            'backend_verified': True,
            'task_solved': False,
            'outcome': 'tied_scores',
        }))
        self.accepted_outcomes = 'tied_scores,budget_exhausted'
        manifest = self.package(require_done=False)
        self.assertFalse(manifest['require_done'])
        self.assertEqual(manifest['accepted_outcomes'], ['budget_exhausted', 'tied_scores'])
        self.assertTrue(manifest['check']['backend_verified'])
        self.assertFalse(manifest['check']['task_solved'])

    def test_require_done_rejects_inconsistent_success_fields(self):
        for solved, outcome in [(False, 'task_solved'), (True, 'tied_scores'),
                                ('true', 'task_solved'), (None, 'task_solved')]:
            with self.subTest(solved=solved, outcome=outcome):
                self.report.write_text(json.dumps({
                    'backend_verified': True, 'task_solved': solved, 'outcome': outcome,
                }))
                self.accepted_outcomes = 'task_solved,tied_scores'
                self.assertEqual(self.package(), 2)

    def test_workflow_accepts_actual_silence_outcome(self):
        # Exercise the outcome list used by CI rather than a separate test copy.
        workflow = (ROOT / '.github/workflows/neural-docker.yml').read_text()
        self.accepted_outcomes = workflow.split('--accepted-outcomes ', 1)[1].splitlines()[0].strip()
        self.report.write_text(json.dumps({
            'backend_verified': True, 'task_solved': False, 'outcome': 'silent_readouts',
        }))
        manifest = self.package(require_done=False)
        self.assertEqual(manifest['check']['outcome'], 'silent_readouts')
        self.assertFalse(manifest['check']['task_solved'])

    def test_archive_is_reproducible_for_identical_inputs(self):
        first = self.root / 'first.tar.gz'
        second = self.root / 'second.tar.gz'
        self.package(first)
        self.package(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(
            hashlib.sha256(first.read_bytes()).hexdigest(),
            hashlib.sha256(second.read_bytes()).hexdigest(),
        )


if __name__ == '__main__':
    unittest.main()
