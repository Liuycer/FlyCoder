from dataclasses import asdict
import json
from pathlib import Path

from .state import Action, State, reward_for


class Controller:
    def __init__(self, sandbox, policy, coder, runner, task: str, run_dir: Path,
                 max_steps: int = 12, max_attempts: int = 3, explore_actions: bool = False, seed: int = 0):
        if max_steps < 1 or max_attempts < 1:
            raise ValueError("Budgets must be positive")
        self.sandbox, self.policy, self.coder, self.runner = sandbox, policy, coder, runner
        self.task, self.run_dir = task, run_dir
        self.max_steps, self.max_attempts = max_steps, max_attempts
        self.explore_actions, self.seed = explore_actions, seed
        self.state = State()
        self.analysis = ""
        self.test_output = ""
        self.tested_fingerprint = None

    def allowed(self) -> list:
        s = self.state
        if self.explore_actions:
            if not s.read:
                return [Action.READ]
            if s.tested and s.passed:
                return [Action.DONE]
            if s.tested:
                if s.attempts >= self.max_attempts:
                    return []
                return ([Action.READ] if s.last_action != Action.READ.value else []) + [Action.RETRY]
            actions = [Action.READ] if s.last_action != Action.READ.value else []
            if s.attempts < self.max_attempts:
                actions.append(Action.EDIT)
            if s.edited:
                actions.append(Action.TEST)
            return actions
        if not s.read:
            return [Action.READ]
        if s.tested:
            if s.passed:
                return [Action.DONE]
            return [Action.RETRY] if s.attempts < self.max_attempts else []
        if s.edited and s.last_action != Action.RETRY.value:
            return [Action.TEST]
        return [Action.READ, Action.EDIT] if s.attempts < self.max_attempts else []

    def emit(self, record: dict) -> None:
        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def finish(self, status: str, reason: str) -> dict:
        summary = {"status": status, "reason": reason, "state": self.state.snapshot(),
                   "sandbox": str(self.sandbox.root),
                   "policy": type(self.policy).__name__, "coder": type(self.coder).__name__,
                   "explore_actions": self.explore_actions, "seed": self.seed,
                   "last_neural_trace": getattr(self.policy, 'last_trace', None)}
        (self.run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (self.run_dir / "changes.patch").write_text(self.sandbox.diff(), encoding="utf-8")
        return summary

    def run(self) -> dict:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.policy.reset(seed=self.seed)
            # Baseline is validation plumbing, not an additional action in the space.
            baseline = self.runner.run(self.sandbox.root)
            self.test_output = baseline.output
            self.emit({"event": "baseline", **asdict(baseline)})
            for step in range(1, self.max_steps + 1):
                s = self.state
                s.step = step
                allowed = self.allowed()
                if not allowed:
                    return self.finish("exhausted", "Edit attempt budget exhausted")
                observation = s.encode(self.max_steps, self.max_attempts)
                action = self.policy.select(observation, allowed)
                if action not in allowed:
                    raise ValueError("Controller rejected illegal action: " + str(action))
                detail = {}
                if action == Action.READ:
                    self.analysis = self.coder.read(self.task, self.sandbox.context())
                    s.read = True
                elif action == Action.EDIT:
                    s.attempts += 1
                    changes = self.coder.edit(self.task, self.sandbox.context(),
                                              sorted(self.sandbox.editable), self.analysis,
                                              self.test_output, s.attempts)
                    self.sandbox.apply(changes)
                    s.edited, s.tested, s.passed, s.timed_out = True, False, False, False
                    self.tested_fingerprint = None
                elif action == Action.TEST:
                    before = self.sandbox.fingerprint()
                    result = self.runner.run(self.sandbox.root)
                    after = self.sandbox.fingerprint()
                    if before != after:
                        raise ValueError("Tests modified tracked files; result rejected")
                    self.tested_fingerprint = after
                    self.test_output = result.output
                    s.tested, s.passed, s.timed_out = True, result.passed, result.timed_out
                    detail = asdict(result)
                elif action == Action.RETRY:
                    # Keep the candidate and failure output so the next edit can improve it.
                    s.retries += 1
                    s.edited = False
                    s.tested, s.passed, s.timed_out = False, False, False
                    self.tested_fingerprint = None
                elif action == Action.DONE:
                    if not s.passed or self.tested_fingerprint != self.sandbox.fingerprint():
                        raise ValueError("DONE requires passing tests on the current snapshot")
                s.changed_files = self.sandbox.changed_count()
                s.last_action = action.value
                s.reward = reward_for(action, s)
                self.policy.feedback(s.reward, s.encode(self.max_steps, self.max_attempts))
                self.emit({"event": "action", "action": action.value,
                           "observation": observation, "allowed": [a.value for a in allowed],
                           "state": s.snapshot(), "detail": detail,
                           "neural_trace": getattr(self.policy, "last_trace", None)})
                print(f"{step:02d} {action.value:5s} reward={s.reward:+.2f} "
                      f"attempts={s.attempts} passed={s.passed}", flush=True)
                if action == Action.DONE:
                    return self.finish("done", "Current snapshot passed the configured unittest suite")
            return self.finish("exhausted", "Step budget exhausted")
        except Exception as exc:
            self.emit({"event": "error", "type": type(exc).__name__, "message": str(exc)})
            return self.finish("error", str(exc))
        finally:
            self.policy.close()
