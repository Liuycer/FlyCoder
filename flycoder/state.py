from dataclasses import asdict, dataclass
from enum import Enum
from typing import Optional


class Action(str, Enum):
    READ = "READ"
    EDIT = "EDIT"
    TEST = "TEST"
    RETRY = "RETRY"
    DONE = "DONE"


@dataclass
class State:
    step: int = 0
    attempts: int = 0
    retries: int = 0
    read: bool = False
    edited: bool = False
    tested: bool = False
    passed: bool = False
    timed_out: bool = False
    changed_files: int = 0
    reward: float = 0.0
    last_action: Optional[str] = None

    def encode(self, max_steps: int, max_attempts: int) -> dict:
        """Versioned, normalized stimulus vector; no source code enters the policy."""
        return {"schema": "flycoder.state.v1", "features": {
            "read": float(self.read), "edited": float(self.edited),
            "tested": float(self.tested), "passed": float(self.passed),
            "timed_out": float(self.timed_out),
            "step_fraction": min(self.step / max_steps, 1.0),
            "attempt_fraction": min(self.attempts / max_attempts, 1.0),
            "change_fraction": min(self.changed_files / 10, 1.0),
            "reward": self.reward,
            **{"last_" + a.value: float(self.last_action == a.value) for a in Action},
        }}

    def snapshot(self) -> dict:
        return asdict(self)


def reward_for(action: Action, state: State) -> float:
    if action == Action.TEST:
        return -0.5 if state.timed_out else (1.0 if state.passed else -0.3)
    return -0.1 if action == Action.RETRY else (0.0 if action == Action.DONE else -0.01)
