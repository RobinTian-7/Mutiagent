"""Per-request hard wall-clock timeout for LLM calls.

A real benchmark run once hung for over an hour on a single stalled provider call
(ESTABLISHED socket, ~0% CPU) routed through a flaky proxy; the OpenAI client's
own httpx timeout never freed it because the proxy trickled keep-alive bytes that
kept resetting the read deadline. ``TimeoutLLMClient`` adds a *hard* wall-clock
budget per ``complete`` call so a hung request fails fast instead of freezing the
whole run.

This guard lives in ``exp_graph`` (not the caller) so it can be applied
**universally at client construction** via :func:`exp_graph.llm.factory.create_llm_client`.
That matters because several engine-internal sites build their own clients
(role clients, the graph-generation candidate evaluator, the LLM insight
minister, and the ``ProtocolRunner`` fallback); wrapping only the client a caller
explicitly threads in would leave those internal calls unguarded.

Why a bare daemon thread (not ``concurrent.futures``): a Python thread cannot be
forcibly killed, so the only way to *abandon* a stuck blocking call is to run it
on a ``daemon=True`` thread and stop waiting via ``join(timeout)``. When we give
up, the worker keeps running in the background but, being a daemon, will NOT
block interpreter exit. A ``ThreadPoolExecutor`` used as a context manager (or
``shutdown(wait=True)``) would re-block on the hung worker at exit, reintroducing
the exact freeze we are trying to eliminate, so it is deliberately avoided here.
"""
# ============================================================
# 【模块导读】LLM 调用的每请求硬性墙钟超时(wall-clock timeout)守卫。
# 背景：真实基准跑曾在单个卡死的供应商调用上挂起一小时以上(不稳定代理零星回送
# keep-alive 字节不断重置读超时，OpenAI 客户端自带的 httpx 超时因而始终不触发)。
# TimeoutLLMClient 给每次 complete 调用加硬性墙钟预算，挂死请求快速失败而非冻结全局。
# 守卫放在 exp_graph 内而非调用方：create_llm_client 构建客户端时统一套上，引擎内部
# 自建客户端(角色客户端、图生成候选评估器、insight minister、ProtocolRunner 兜底)同样受保护。
# 用裸 daemon 线程而非 concurrent.futures：Python 线程无法强杀，只能 join(timeout) 后放弃
# (daemon 不阻塞解释器退出)；线程池退出时会重新阻塞在挂死线程上，恰好重现要消除的冻结。
# ============================================================

from __future__ import annotations

import threading

from exp_graph.llm.base import LLMClient, LLMResponse


# 【职责】被包装的 LLM complete 调用超出时间预算时抛出的异常。
class LLMTimeoutError(RuntimeError):
    """Raised when a wrapped LLM ``complete`` call exceeds its time budget."""


# 【职责】给内层 LLMClient 包上每请求硬性墙钟超时(wall-clock timeout)。
# - complete 在 daemon 线程上执行内层调用，最多等待 timeout_s 秒。
# - join 后线程仍存活 -> 放弃调用(daemon 线程继续跑但不会阻塞进程退出)，抛 LLMTimeoutError。
# - 内层调用已完成 -> 透传其返回值；其抛出的异常原样重抛。
# - timeout_s 为 None/非正数 -> 不包装，直通内层客户端(离线假客户端瞬时且确定，无需守卫)。
class TimeoutLLMClient:
    """Wrap an inner ``LLMClient`` with a per-request hard wall-clock timeout.

    ``complete`` runs the inner call on a daemon thread and waits at most
    ``timeout_s`` seconds for it. If the thread is still alive after the join the
    call is abandoned (the daemon thread keeps running but cannot block process
    exit) and :class:`LLMTimeoutError` is raised. If the inner call finished, its
    return value is passed through and any exception it raised is re-raised
    unchanged. A non-positive or ``None`` ``timeout_s`` disables wrapping and
    delegates straight to the inner client (fakes are instant/deterministic).
    """

    def __init__(self, inner: LLMClient, timeout_s: float | None) -> None:
        self._inner = inner
        self._timeout_s = timeout_s

    # 【职责】带墙钟预算执行一次内层 complete；超时则放弃 daemon 线程并抛 LLMTimeoutError。
    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
        **kwargs: object,
    ) -> LLMResponse:
        # 中文：透明转发额外关键字(如 json_mode)——仅当调用方显式传入时才转发，
        #   这样不接受新参数的内层客户端在默认调用下仍能工作(与 RetryLLMClient 一致)。
        # Transparently forward extra keywords (e.g. json_mode) only when the
        # caller passed them, so inner clients that predate a new parameter still
        # work on default calls — mirroring RetryLLMClient's *args/**kwargs pass.
        # 中文：无预算 -> 行为与内层客户端完全一致(不开线程、不加守卫)。
        # No budget -> behave exactly like the inner client (no thread, no guard).
        if self._timeout_s is None or self._timeout_s <= 0:
            return self._inner.complete(prompt, model_name, temperature, **kwargs)

        # 中文：存放工作线程结果的容器。列表原地变更，使调用线程能读到 daemon 线程
        #   在 join 结束前存入的内容。
        # Holder for the worker's outcome. Lists are mutated in place so the
        # calling thread reads whatever the daemon thread stored before joining.
        result: list[LLMResponse] = []
        error: list[BaseException] = []

        def _run() -> None:
            try:
                result.append(
                    self._inner.complete(
                        prompt, model_name, temperature, **kwargs
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - preserved + re-raised below
                error.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(self._timeout_s)

        if thread.is_alive():
            # 中文：调用挂死——放弃该 daemon 线程并快速失败。绝不做无超时的 join
            #   (那会重新引入我们要消除的冻结)。
            # Hung call: abandon the daemon thread and fail fast. We do NOT join
            # without a timeout (that would reintroduce the freeze).
            raise LLMTimeoutError(f"LLM call exceeded {self._timeout_s}s")

        if error:
            raise error[0]
        return result[0]
