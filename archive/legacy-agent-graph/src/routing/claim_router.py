"""Claim routing — reinforced routing over claims.

Paper reference (Sec 4.2, Eq. 3):
  P(c_i | F_t) = x_i(t)^β / Σ_j x_j(t)^β

  x_i(t) = accumulated coordination activity of claim c_i
  β > 0 controls reinforcement strength
  β = 0 → uniform routing

This module is decoupled from topology routing.
Topology routing: who can communicate with whom (physical graph).
Claim routing: which existing claim gets selected for further reasoning.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

import numpy as np

from src.schemas.claims import Claim


class ClaimRouter(ABC):
    """Abstract interface for claim selection policies."""

    @abstractmethod
    def select_claim(self, candidates: list[Claim], activity: dict[str, int]) -> Claim:
        """Select a claim from candidates based on routing policy.

        Args:
            candidates: claims visible to the acting agent.
            activity: mapping from claim_id to accumulated coordination activity x_i(t).

        Returns:
            The selected claim.
        """
        ...


class UniformRouter(ClaimRouter):
    """Uniform random selection (β = 0 baseline)."""

    def select_claim(self, candidates: list[Claim], activity: dict[str, int]) -> Claim:
        return random.choice(candidates)


class ReinforcedRouter(ClaimRouter):
    """Reinforced routing per Paper Eq. 3.

    P(c_i | F_t) = x_i(t)^β / Σ_j x_j(t)^β

    ASSUMPTION (A9): β defaults to 0.15, matching empirical β̂ for GPT-4o-mini.
    """

    def __init__(self, beta: float = 0.15):
        self.beta = beta

    def select_claim(self, candidates: list[Claim], activity: dict[str, int]) -> Claim:
        if not candidates:
            raise ValueError("No candidate claims for routing")

        # Get activity counts; default to 1 for claims with no prior activity
        # (avoids zero probability for new claims)
        weights = np.array(
            [max(activity.get(c.claim_id, 0), 1) ** self.beta for c in candidates],
            dtype=np.float64,
        )

        # Normalize to probabilities
        total = weights.sum()
        if total == 0:
            probs = np.ones(len(candidates)) / len(candidates)
        else:
            probs = weights / total

        idx = np.random.choice(len(candidates), p=probs)
        return candidates[idx]
