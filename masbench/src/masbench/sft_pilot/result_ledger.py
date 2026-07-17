"""External append-only result ledger (v5 Stage 9).

Reserved by the runtime authority code-source law (``result_ledger``) so its
exact bytes are pinned from the first sealed experiment onward.  The ledger
implementation lands with the Stage 9 closure; until then the module exports
nothing and no result row can be written from here.
"""

from __future__ import annotations

__all__: list[str] = []
