"""Append-only event trace logger.

Paper reference (Appendix B.3):
  "We record fine-grained coordination traces at the event level to enable
   reconstruction of coordination structures."

All events and claims are appended to JSONL files. The trace is the primary
runtime record; graphs are reconstructed from traces rather than maintained
as live objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.schemas.claims import Claim
from src.schemas.events import Event


class TraceLogger:
    """Append-only logger for events and claims."""

    def __init__(self, output_dir: str | Path, run_id: str = "run_0"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id

        self._event_path = self.output_dir / "event_trace.jsonl"
        self._claim_path = self.output_dir / "claims.jsonl"

        # In-memory buffers for fast access during simulation
        self.events: list[Event] = []
        self.claims: list[Claim] = []
        self._claim_index: dict[str, Claim] = {}

    def log_event(self, event: Event) -> None:
        """Append an event to the trace."""
        event.run_id = self.run_id
        self.events.append(event)
        with open(self._event_path, "a") as f:
            f.write(event.model_dump_json() + "\n")

    def log_claim(self, claim: Claim) -> None:
        """Append a claim to the trace."""
        self.claims.append(claim)
        self._claim_index[claim.claim_id] = claim
        with open(self._claim_path, "a") as f:
            f.write(claim.model_dump_json() + "\n")

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        """Look up a claim by ID."""
        return self._claim_index.get(claim_id)

    def get_root_claim_id(self, claim_id: str) -> str:
        """Trace lineage to find root claim.

        Paper (Appendix B.5): "Each claim is associated with a root_claim_id,
        inherited from its earliest ancestor."
        """
        claim = self._claim_index.get(claim_id)
        if claim is None:
            return claim_id
        if not claim.parent_claim_ids:
            return claim.claim_id
        return claim.root_claim_id

    def get_claims_by_root(self, root_claim_id: str) -> list[Claim]:
        """Get all claims in a cascade."""
        return [c for c in self.claims if c.root_claim_id == root_claim_id]

    def get_events_by_root(self, root_claim_id: str) -> list[Event]:
        """Get all events in a cascade."""
        return [e for e in self.events if e.root_claim_id == root_claim_id]

    def flush(self) -> None:
        """No-op — we write incrementally. Provided for API completeness."""
        pass
