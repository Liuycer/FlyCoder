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
    def __init__(self, backend: NeuralBackend, tie_extra_windows: int = 0):
        if type(tie_extra_windows) is not int or not 0 <= tie_extra_windows <= 2:
            raise ValueError("tie_extra_windows must be an integer from 0 to 2")
        self.tie_extra_windows = tie_extra_windows
        self.selection_calls = 0
        self.backend = backend
        self.last_trace = None
        self.last_decision = None

    def reset(self, seed: int = 0) -> None:
        self.last_trace = None
        self.last_decision = None
        self.selection_calls = 0
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
            scores = self.measure(observation['features'], allowed)
            if self.last_trace is None:
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

    def measure(self, features, allowed):
        if not self.tie_extra_windows:
            return self.backend.stimulate_and_step(features)
        self.selection_calls += 1
        windows = []
        for _ in range(1 + self.tie_extra_windows):
            try:
                self.backend.stimulate_and_step(features)
            except NeuralSelectionError as exc:
                if exc.reason != 'silent_readouts':
                    raise
                # Silence remains a stop, not a trigger for extra sampling.
                if not windows:
                    windows.append(deepcopy(self.backend.last_trace))
                    self.last_trace = self.aggregate(windows)
                    raise
            window = deepcopy(getattr(self.backend, 'last_trace', None))
            if not isinstance(window, dict) or 'readout_spikes' not in window:
                raise ValueError('Accumulation requires measured spike counts')
            windows.append(window)
            self.last_trace = self.aggregate(windows)
            scores = self.last_trace['scores_hz']
            best = max(scores[a.value] for a in allowed)
            if sum(scores[a.value] == best for a in allowed) == 1:
                break
        return self.last_trace['scores_hz']

    def aggregate(self, windows):
        duration = sum(w['simulated_ms'] for w in windows)
        counts = {a: sum(w['readout_spikes'][a] for w in windows)
                  for a in windows[0]['readout_spikes']}
        sizes = windows[0]['provenance']['readout_sizes']
        return {'schema': 'flycoder.neural-accumulation.v1',
                'call': self.selection_calls, 'tie_extra_windows': self.tie_extra_windows,
                'windows': windows, 'simulated_ms': duration,
                'cumulative_simulated_ms': windows[-1]['cumulative_simulated_ms'],
                'readout_spikes': counts,
                'scores_hz': {a: counts[a] / sizes[a] * 1000 / duration for a in counts}}

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
