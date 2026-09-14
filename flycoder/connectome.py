"""The policy sees numeric observations and chooses one of five actions only."""
from abc import ABC, abstractmethod
from copy import deepcopy
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


class NeuralSelectionError(RuntimeError):
    """A measured policy outcome, with a stable machine-readable reason."""
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class NeuralConnectome(ConnectomeAdapter):
    """Record every selection attempt before enforcing the no-fallback rule."""
    def __init__(self, backend: NeuralBackend):
        self.backend = backend
        self.last_trace = None
        self.last_decision = None

    def reset(self, seed: int = 0) -> None:
        self.last_trace = None
        self.last_decision = None
        self.backend.reset(seed)

    def select(self, observation: dict, allowed: Sequence[Action]) -> Action:
        import math
        self.last_trace = None
        if hasattr(self.backend, 'last_trace'):
            self.backend.last_trace = None
        self.last_decision = {
            'observation': deepcopy(observation), 'allowed': [a.value for a in allowed],
            'status': 'pending', 'reason': None, 'selected_action': None,
            'scores_hz': None, 'best_score_hz': None, 'top_margin_hz': None,
            'tied_actions': [],
        }
        try:
            scores = self.backend.stimulate_and_step(observation['features'])
            self.last_trace = deepcopy(getattr(self.backend, 'last_trace', None))
            if not isinstance(scores, dict) or not allowed or any(
                isinstance(scores.get(a.value), bool)
                or not isinstance(scores.get(a.value), (int, float))
                or not math.isfinite(scores[a.value]) for a in allowed
            ):
                raise ValueError('Backend must return finite scores for every action')
            self.last_decision['scores_hz'] = dict(scores)
            best = max(scores[a.value] for a in allowed)
            tied = [a.value for a in allowed if scores[a.value] == best]
            ordered = sorted((scores[a.value] for a in allowed), reverse=True)
            self.last_decision.update(best_score_hz=best, tied_actions=tied,
                                      top_margin_hz=ordered[0] - ordered[1] if len(ordered) > 1 else None)
            if getattr(self.backend, 'requires_distinct_scores', False) and len(tied) > 1:
                raise NeuralSelectionError('tied_scores', 'Legal neural action scores are tied; no rule fallback')
            action = max(allowed, key=lambda a: scores[a.value])
            self.last_decision.update(status='selected', selected_action=action.value)
            if self.last_trace is not None:
                self.last_trace['selected_action'] = action.value
            return action
        except Exception as exc:
            if self.last_trace is None:
                self.last_trace = deepcopy(getattr(self.backend, 'last_trace', None))
            reason = exc.reason if isinstance(exc, NeuralSelectionError) else 'backend_error'
            self.last_decision.update(status='rejected', reason=reason)
            if reason == 'silent_readouts' and self.last_trace:
                self.last_decision['scores_hz'] = deepcopy(self.last_trace.get('scores_hz'))
            raise

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
