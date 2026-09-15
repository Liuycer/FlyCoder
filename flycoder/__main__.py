import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from .connectome import MockConnectome, RandomConnectome, NeuralConnectome
from .controller import Controller
from .llm import MockCodingAdapter, OpenAICodingAdapter, ChatCompletionsCodingAdapter
from .sandbox import GitSandbox
from .testing import TestRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="FlyCoder v0.2 experimental coding controller")
    parser.add_argument("command", choices=["demo", "run"], nargs="?", default="demo")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--editable", action="append", help="Existing editable file; repeat as needed")
    parser.add_argument("--llm", choices=["mock", "openai", "deepseek", "chat-completions"], default=os.getenv("LLM_ADAPTER", "mock"))
    parser.add_argument("--connectome", choices=["mock", "random", "malecns", "doomfly", "flywire"],
                        default=os.getenv("CONNECTOME_ADAPTER", "mock"))
    parser.add_argument("--runs", type=Path, default=Path(os.getenv("FLYCODER_RUNS", "runs")))
    parser.add_argument("--max-steps", type=int, default=int(os.getenv("MAX_STEPS", "12")))
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("MAX_ATTEMPTS", "3")))
    parser.add_argument("--test-timeout", type=float, default=float(os.getenv("TEST_TIMEOUT", "15")))
    parser.add_argument("--mock-first-pass", action="store_true", help="Skip deliberate first-edit failure")
    parser.add_argument('--tie-extra-windows', type=int, choices=[0, 1, 2], default=0, help='Experimental: accumulate up to this many extra neural windows on ties')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--explore-actions', action='store_true', help='Use the broader action mask for baseline comparisons')
    parser.add_argument('--neural-control', choices=['intact', 'no-stimulus', 'disconnected', 'shuffled-readout'], default='intact')
    args = parser.parse_args()
    if args.tie_extra_windows and args.connectome not in {'malecns', 'doomfly'}:
        parser.error('--tie-extra-windows requires a neural backend')
    if args.connectome == 'flywire':
        parser.error('FlyWire is not implemented; MaleCNS mappings cannot be reused for FlyWire')
    if args.connectome not in {'mock', 'random', 'malecns', 'doomfly'}:
        parser.error('Unknown CONNECTOME_ADAPTER')
    if args.command == "run" and (not args.repo or not args.task or not args.editable):
        parser.error("run requires --repo, --task and at least one --editable")
    if args.max_steps < 1 or args.max_attempts < 1 or args.test_timeout <= 0:
        parser.error("Budgets and timeout must be positive")
    repo = args.repo or Path(__file__).resolve().parent / "examples" / "buggy_repo"
    task = args.task or "Fix average(values): correct arithmetic mean; empty input must raise ValueError."
    editable = args.editable or ["calculator.py"]
    run_dir = args.runs.resolve() / uuid4().hex
    try:
        if args.llm == "openai":
            coder = OpenAICodingAdapter.from_env()
        elif args.llm in {"deepseek", "chat-completions"}:
            coder = ChatCompletionsCodingAdapter.from_env(args.llm)
        elif args.llm == "mock":
            coder = MockCodingAdapter(not args.mock_first_pass)
        else:
            raise ValueError("Unknown LLM_ADAPTER")
        if args.connectome in {'malecns', 'doomfly'}:
            from .malecns import MaleCNSBackend
            policy = NeuralConnectome(MaleCNSBackend(control=args.neural_control), args.tie_extra_windows)
        elif args.connectome == 'random':
            policy = RandomConnectome()
        else:
            policy = MockConnectome()
        sandbox = GitSandbox(repo, run_dir / "repo", editable)
        sandbox.create()
        result = Controller(sandbox, policy, coder, TestRunner(args.test_timeout),
                            task, run_dir, args.max_steps, args.max_attempts,
                            args.explore_actions or args.connectome != 'mock', args.seed).run()
    except Exception as exc:
        print("FlyCoder setup failed: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "artifacts": str(run_dir)}, ensure_ascii=False))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
