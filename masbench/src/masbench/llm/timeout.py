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
# ============================================================
# 【模块导读】向后兼容垫片。每次请求的硬性挂钟超时守卫现已迁到 exp_graph，以便在
# 客户端构造时“普遍”施加（多个引擎内部站点会自建客户端：角色客户端、图生成候选评估器、
# 洞察 minister、ProtocolRunner 兜底）；只包 masbench 传入的客户端会漏掉那些，任一处
# 卡死就会冻结整个运行。本模块重导出该守卫，让已有 import 继续可用。
# ============================================================

from __future__ import annotations

from exp_graph.llm.timeout import LLMTimeoutError, TimeoutLLMClient

__all__ = ["LLMTimeoutError", "TimeoutLLMClient"]
