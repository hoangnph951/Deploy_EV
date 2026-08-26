from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from src.packages.core.policies.domain.entities import PolicyConfig


class PolicyConfigRepository(Protocol):
    def get_active_policy(self) -> PolicyConfig | None: ...


class PolicyConfigService:
    """Read the active policy once per service instance.

    Tests can provide an explicit override, while runtime reads the versioned
    policy from persistence. ``clear_cache`` is the deliberate reload boundary
    after an administrative policy update.
    """

    def __init__(
        self,
        repository: PolicyConfigRepository | None = None,
        *,
        override: PolicyConfig | None = None,
    ) -> None:
        if repository is None and override is None:
            raise ValueError("A policy repository or override is required.")
        self._repository = repository
        self._override = override

    @lru_cache(maxsize=1)
    def get_active_policy(self) -> PolicyConfig:
        if self._override is not None:
            return self._override

        if self._repository is None:
            raise RuntimeError("Policy repository is not configured.")

        policy = self._repository.get_active_policy()
        if policy is None:
            raise RuntimeError("No active policy configuration is available.")
        return policy

    def clear_cache(self) -> None:
        self.get_active_policy.cache_clear()
