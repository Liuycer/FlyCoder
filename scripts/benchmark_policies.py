"""Matched action-budget evaluation; fixtures by default, paid LLM only with --live."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flycoder.connectome import MockConnectome, RandomConnectome, NeuralConnectome
from flycoder.controller import Controller
from flycoder.llm import CodingAdapter, ChatCompletionsCodingAdapter, OpenAICodingAdapter
from flycoder.sandbox import GitSandbox
from flycoder.testing import TestRunner
from scripts.check_neural_run import validate_run


class FixtureCoder(CodingAdapter):
    """Deterministic candidate schedule; NOT an LLM or coding benchmark score."""
    def __init__(self, task):
        self.task = task
    def read(self, task, files):
        return 'Offline candidate fixture; inspect requirements and tests.'
    def edit(self, task, files, editable, analysis, test_output, attempt):
        name = 'solution.py' if attempt >= self.task['repair_after'] else 'partial.py'
        return {'module.py': (ROOT / 'benchmarks/tasks' / self.task['id'] / name).read_text()}


def configured_coder():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line = line[7:]
            key, value = line.split('=', 1)
            parts = shlex.split(value, comments=True)
            if len(parts) > 1: raise ValueError('Invalid .env quoting')
            if key.strip().startswith(('LLM_', 'OPENAI_', 'DEEPSEEK_')):
                os.environ[key.strip()] = parts[0] if parts else ''
    name = os.getenv('LLM_ADAPTER')
    if name == 'openai': return OpenAICodingAdapter.from_env()
    if name in {'chat-completions', 'deepseek'}: return ChatCompletionsCodingAdapter.from_env(name)
    raise ValueError('--live requires a configured real LLM adapter')


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--controllers', nargs='+', choices=['mock','random','malecns','accumulating'], default=['mock','random','malecns','accumulating'])
    p.add_argument('--seeds', nargs='+', type=int, default=[0,1,2])
    p.add_argument('--output', type=Path)
    p.add_argument('--live', action='store_true')
    args = p.parse_args()
    output = args.output or ROOT / 'research' / ('benchmark-' + uuid4().hex[:10])
    output.mkdir(parents=True, exist_ok=False)
    tasks = json.loads((ROOT/'benchmarks/tasks.json').read_text())
    source_hash = hashlib.sha256()
    for file in sorted((ROOT/'benchmarks').rglob('*.py')):
        source_hash.update(str(file.relative_to(ROOT)).encode() + file.read_bytes())
    source_hash.update((ROOT/'benchmarks/tasks.json').read_bytes())
    rows=[]
    report={'schema':'flycoder.benchmark.v1','suite_sha256':source_hash.hexdigest(),
            'platform':platform.platform(),'real_llm':args.live,'seeds':args.seeds,
            'budgets':{'max_steps':12,'max_attempts':3,'test_timeout_seconds':15,
                       'neural_window_ms':100,'max_neural_windows_per_run':36},
            'limitations':'Fixtures test orchestration, not LLM coding ability. Seeds affect random policy; fixed neural reset is deterministic. Extra simulation is measured, not equal compute. Live monetary cost unavailable; consult provider billing. No learning or code understanding by connectome.',
            'results':rows}
    for task in tasks:
        for seed in args.seeds:
            for name in args.controllers:
                coder = configured_coder() if args.live else FixtureCoder(task)
                calls={'read':0,'edit':0}
                for op in calls:
                    original=getattr(coder,op)
                    def counted(*a,_op=op,_fn=original,**kw):
                        calls[_op]+=1
                        return _fn(*a,**kw)
                    setattr(coder,op,counted)
                if name in {'malecns','accumulating'}:
                    from flycoder.malecns import MaleCNSBackend
                    policy=NeuralConnectome(MaleCNSBackend(),2 if name=='accumulating' else 0)
                else:
                    policy=MockConnectome() if name=='mock' else RandomConnectome()
                run=output/f'{task["id"]}-{seed}-{name}'
                box=GitSandbox(ROOT/'benchmarks/tasks'/task['id']/'repo',run/'repo',task['editable']);box.create()
                start=time.perf_counter()
                with (run/'console.log').open('w') as log,contextlib.redirect_stdout(log):
                    result=Controller(box,policy,coder,TestRunner(15),task['task'],run,12,3,True,seed).run()
                events=[json.loads(x) for x in (run/'events.jsonl').read_text().splitlines()]
                evidence=validate_run(run/'summary.json') if name in {'malecns','accumulating'} else None
                traces=[e['neural_trace'] for e in events if e.get('neural_trace')]
                windows=[w for t in traces for w in t.get('windows',[t])]
                if any(w['simulated_ms'] != 100 for w in windows):
                    raise ValueError('Matched benchmark requires 100 ms neural windows')
                ties=0
                for e in events:
                    trace=e.get('neural_trace')
                    if trace:
                        first=trace.get('windows',[trace])[0]; allowed=e['allowed']
                        best=max(first['scores_hz'][a] for a in allowed)
                        ties+=sum(first['scores_hz'][a]==best for a in allowed)>1
                row={'task':task['id'],'seed':seed,'controller':name,'status':result['status'],
                     'task_solved':result['status']=='done','reason':result['reason'],
                     'steps':sum(e['event']=='action' for e in events),'attempts':result['state']['attempts'],
                     'tie_decisions':ties,'terminal_tie':(result.get('last_neural_decision') or {}).get('reason')=='tied_scores',
                     'neural_windows':len(windows),'simulated_ms':sum(w['simulated_ms'] for w in windows),
                     'wall_seconds':time.perf_counter()-start,'coding_calls':calls,
                     'llm_calls':sum(calls.values()) if args.live else 0,
                     'cost_usd':None if args.live else 0,'evidence':evidence,'artifacts':str(run)}
                rows.append(row)
                report['aggregate']={n:{'runs':len(r:=[x for x in rows if x['controller']==n]),
                    'successes':sum(x['task_solved'] for x in r),'success_rate':sum(x['task_solved'] for x in r)/len(r),
                    'tie_decisions':sum(x['tie_decisions'] for x in r),'terminal_ties':sum(x['terminal_tie'] for x in r),
                    'mean_steps':sum(x['steps'] for x in r)/len(r),
                    'coding_calls':sum(sum(x['coding_calls'].values()) for x in r),
                    'simulated_ms':sum(x['simulated_ms'] for x in r)} for n in args.controllers if any(x['controller']==n for x in rows)}
                (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
                print(task['id'],seed,name,row['status'],flush=True)
    print(json.dumps(report['aggregate'],indent=2))

if __name__=='__main__': main()
