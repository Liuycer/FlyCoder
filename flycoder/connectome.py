"""The policy sees numeric observations and chooses one of five actions only."""
from abc import ABC, abstractmethod
from typing import Sequence

from .state import Action


class ConnectomeAdapter(ABC):
    @abstractmethod
    def reset(self, seed: int = 0) -> None:
        pass

    @abstractmethod
    def select(self, observation: dict, allowed: Sequence[Action]) -> Action:
        pass

    @abstractmethod
    def feedback(self, reward: float, observation: dict) -> None:
        pass

    def close(self) -> None:
        pass


class MockConnectome(ConnectomeAdapter):
    """Deterministic workflow policy, NOT a biological simulation or learned policy."""
    def reset(self, seed: int = 0) -> None:
        self.last_reward = 0.0

    def select(self, observation: dict, allowed: Sequence[Action]) -> Action:
        f = observation["features"]
        if not f["read"]:
            action = Action.READ
        elif f["last_RETRY"]:
            action = Action.EDIT
        elif not f["edited"]:
            action = Action.EDIT
        elif not f["tested"]:
            action = Action.TEST
        else:
            action = Action.DONE if f["passed"] else Action.RETRY
        if action not in allowed:
            raise RuntimeError("Mock policy has no legal action within the budget")
        return action

    def feedback(self, reward: float, observation: dict) -> None:
        self.last_reward = reward  # Logged signal only; no online learning in this prototype.


class NeuralBackend(ABC):
    """Future local MaleCNS/DOOMFLY/FlyWire bridge, not an upstream API claim."""
    @abstractmethod
    def reset(self, seed: int) -> None:
        pass

    @abstractmethod
    def stimulate_and_step(self, features: dict) -> dict:
        """Apply configured sensory mapping, advance dynamics, return action scores."""
        pass

    @abstractmethod
    def reward(self, value: float) -> None:
        pass

    def close(self) -> None:
        pass


class NeuralConnectome(ConnectomeAdapter):
    """Select legal actions from an explicitly injected neural backend."""
    def __init__(self, backend: NeuralBackend):
        self.backend = backend

    def reset(self, seed: int = 0) -> None:
        self.backend.reset(seed)

    def select(self, observation: dict, allowed: Sequence[Action]) -> Action:
        import math
        scores = self.backend.stimulate_and_step(observation["features"])
        if not allowed or any(
            not isinstance(scores.get(a.value), (int, float))
            or not math.isfinite(scores[a.value]) for a in allowed
        ):
            raise ValueError("Backend must return finite scores for every legal action")
        if (getattr(self.backend, 'requires_distinct_scores', False) and len(allowed) > 1
                and sum(scores[a.value] == max(scores[b.value] for b in allowed) for a in allowed) > 1):
            raise RuntimeError("Legal neural action scores are tied; no rule fallback")
        action = max(allowed, key=lambda a: scores[a.value])
        self.last_trace = dict(getattr(self.backend, 'last_trace', {}))
        self.last_trace['selected_action'] = action.value
        return action

    def feedback(self, reward: float, observation: dict) -> None:
        self.backend.reward(reward)

    def close(self) -> None:
        self.backend.close()


class RandomConnectome(MockConnectome):
    """Explicit seeded baseline over the same legal action mask."""
    def reset(self, seed=0):
        import random
        self.rng = random.Random(seed)
        self.last_reward = 0.0

    def select(self, observation, allowed):
        return self.rng.choice(allowed)
