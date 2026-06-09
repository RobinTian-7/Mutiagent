"""The wall-clock timeout guard must be applied UNIVERSALLY at client
construction, so engine-internal sites (role clients, graph-gen candidate
evaluator, insight minister, ProtocolRunner fallback) that build their own
clients via create_llm_client are guarded too -- not just the client a caller
explicitly threads in.
"""
from exp_graph.llm import factory
from exp_graph.llm.fake import FakeLLMClient
from exp_graph.llm.timeout import TimeoutLLMClient


class _RecordingClient:
    """Stand-in for OpenAIChatClient that records its construction kwargs."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def complete(self, prompt, model_name, temperature=None):  # pragma: no cover
        raise AssertionError("not called in these tests")


def test_fake_provider_is_never_wrapped():
    # The fake client is instant/deterministic -> no guard, even if asked.
    client = factory.create_llm_client("fake", timeout_s=5)
    assert isinstance(client, FakeLLMClient)


def test_explicit_timeout_wraps_real_client(monkeypatch):
    monkeypatch.setattr(factory, "OpenAIChatClient", _RecordingClient)
    client = factory.create_llm_client("openai", timeout_s=5)
    assert isinstance(client, TimeoutLLMClient)
    assert client._timeout_s == 5
    assert isinstance(client._inner, _RecordingClient)


def test_env_timeout_wraps_real_client(monkeypatch):
    # Internal callers don't pass timeout_s; they inherit the env budget that
    # masbench sets from cfg.request_timeout.
    monkeypatch.setattr(factory, "OpenAIChatClient", _RecordingClient)
    monkeypatch.setenv("EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT", "7")
    client = factory.create_llm_client("openai")
    assert isinstance(client, TimeoutLLMClient)
    assert client._timeout_s == 7.0


def test_no_timeout_returns_raw_client(monkeypatch):
    # Back-compat: with no explicit timeout and no env, behaviour is unchanged
    # (raw client, no guard) so existing exp_graph users are unaffected.
    monkeypatch.setattr(factory, "OpenAIChatClient", _RecordingClient)
    monkeypatch.delenv("EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT", raising=False)
    client = factory.create_llm_client("openai")
    assert isinstance(client, _RecordingClient)


def test_role_client_inherits_guard(monkeypatch):
    # create_role_llm_client funnels through create_llm_client, so the role
    # clients used by graph-generation/pipeline/insights are guarded too.
    monkeypatch.setattr(factory, "OpenAIChatClient", _RecordingClient)
    monkeypatch.setenv("EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT", "9")
    from exp_graph.mas.role_llm import create_role_llm_client
    from exp_graph.mas.schemas import MASRuntimeConfig

    runtime = MASRuntimeConfig(llm_provider="openai", model_name="gpt-4o-mini")
    client = create_role_llm_client(runtime, "soldier")
    assert isinstance(client, TimeoutLLMClient)
    assert client._timeout_s == 9.0


def test_role_client_guard_actually_fires(monkeypatch):
    # End-to-end regression for the freeze root cause: the role-client path used
    # by graph-generation / pipeline / insights was UNGUARDED, so a wedged call
    # there froze the whole run. With the universal guard a hung role call must
    # now raise LLMTimeoutError fast instead of hanging.
    import time

    import pytest

    from exp_graph.llm.base import LLMResponse, LLMUsage
    from exp_graph.llm.timeout import LLMTimeoutError

    class _HangingClient:
        def __init__(self, **kwargs) -> None:
            pass

        def complete(self, prompt, model_name, temperature=None):
            time.sleep(5)  # simulate a wedged provider call (releases the GIL)
            return LLMResponse(text="{}", usage=LLMUsage())

    monkeypatch.setattr(factory, "OpenAIChatClient", _HangingClient)
    monkeypatch.setenv("EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT", "0.3")
    from exp_graph.mas.role_llm import create_role_llm_client
    from exp_graph.mas.schemas import MASRuntimeConfig

    runtime = MASRuntimeConfig(llm_provider="openai", model_name="gpt-4o-mini")
    client = create_role_llm_client(runtime, "soldier")

    start = time.perf_counter()
    with pytest.raises(LLMTimeoutError):
        client.complete("p", "m")
    assert time.perf_counter() - start < 2.0  # fired at ~0.3s, not the 5s hang
