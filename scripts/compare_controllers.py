"""Small matched single-task comparison; --live uses configured paid LLM."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shlex
import sys
import time
from uuid import uuid4
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flycoder.connectome import MockConnectome, RandomConnectome, NeuralConnectome
from flycoder.controller import Controller
from flycoder.llm import MockCodingAdapter, ChatCompletionsCodingAdapter, OpenAICodingAdapter
from flycoder.malecns import MaleCNSBackend
from flycoder.sandbox import GitSandbox
from flycoder.testing import TestRunner

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
args = parser.parse_args()
if args.live:
    # Parse assignments as data: never execute .env as shell code or print secrets.
    for line in (ROOT / '.env').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, value = line.split('=', 1)
        parts = shlex.split(value, comments=True)
        if len(parts) > 1:
            raise ValueError('Invalid .env quoting')
        if key.strip().startswith(('LLM_', 'OPENAI_', 'DEEPSEEK_')):
            os.environ[key.strip()] = parts[0] if parts else ''
    provider = os.environ.get('LLM_ADAPTER', '')
    if provider not in {'openai', 'deepseek', 'chat-completions'}:
        raise ValueError('Live comparison requires a real configured LLM')
results = []
for name in ['mock', 'random', 'malecns']:
    if args.live:
        coder = OpenAICodingAdapter.from_env() if provider == 'openai' else ChatCompletionsCodingAdapter.from_env(provider)
    else:
        coder = MockCodingAdapter()
    calls = {'read': 0, 'edit': 0}
    for operation in ['read', 'edit']:
        original = getattr(coder, operation)
        def counted(*a, _fn=original, _op=operation, **kw):
            calls[_op] += 1
            return _fn(*a, **kw)
        setattr(coder, operation, counted)
    policy = {'mock': MockConnectome, 'random': RandomConnectome}.get(name, lambda: NeuralConnectome(MaleCNSBackend()))()
    run_dir = ROOT / 'runs' / (('live-' if args.live else 'offline-') + name + '-' + uuid4().hex[:10])
    sandbox = GitSandbox(ROOT / 'flycoder/examples/buggy_repo', run_dir / 'repo', ['calculator.py'])
    sandbox.create()
    start = time.perf_counter()
    result = Controller(sandbox, policy, coder, TestRunner(),
        'Fix average(values): correct arithmetic mean; empty input must raise ValueError.',
        run_dir, max_steps=12, max_attempts=3, explore_actions=True, seed=0).run()
    row = {'controller': name, 'status': result['status'], 'reason': result['reason'],
           'state': result['state'], 'wall_seconds': time.perf_counter() - start,
           'coding_calls': calls, 'artifacts': str(run_dir), 'real_llm': args.live,
           'model': getattr(coder, 'model', 'scripted-fixture'),
           'endpoint': getattr(coder, 'endpoint', 'https://api.openai.com/v1/responses' if args.live and provider == 'openai' else None)}
    results.append(row)
    print(json.dumps(row), flush=True)
    (ROOT / 'research' / ('comparison-live.json' if args.live else 'comparison-offline.json')).write_text(json.dumps({
        'task': 'bundled average bug', 'seed': 0, 'max_steps': 12, 'max_attempts': 3,
        'limitations': 'One task and one seed per controller; live LLM responses are stochastic. Not evidence of superior strategy or learning.',
        'results': results}, indent=2) + '\n')
