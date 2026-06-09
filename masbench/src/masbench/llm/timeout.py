"""Back-compat shim.

The per-request hard wall-clock timeout guard now lives in ``exp_graph`` so it
can be applied *universally* at client construction (see
:func:`exp_graph.llm.factory.create_llm_client`). That matters because several
engine-internal sites build their own clients (role clients, the graph-generation
candidate evaluator, the insight minister, the ``ProtocolRunner`` fallback);
wrapping only the client masbench threads in would leave those unguarded and a
hung call on one of them would freeze the whole run.

This module re-exports the guard so existing imports keep working.
"""

from __future__ import annotations

from exp_graph.llm.timeout import LLMTimeoutError, TimeoutLLMClient

__all__ = ["LLMTimeoutError", "TimeoutLLMClient"]
