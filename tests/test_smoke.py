"""End-to-end smoke test for the minimal demo."""

from src.simulation.workflow import run_simulation
from src.topology import (
    ChainTopology,
    MeshTopology,
    OnePeerExponentialTopology,
    StarTopology,
    StaticExponentialTopology,
    create_topology,
    topology_names,
)
from src.routing.claim_router import ReinforcedRouter
from src.reconstruction.claim_dag import reconstruct_claim_dag
from src.reconstruction.cascades import extract_cascades
from src.analysis.metrics import (
    compute_cascade_sizes,
    compute_tce,
    compute_top_k_contribution,
)
from src.schemas.claims import Claim
from src.schemas.events import Event


def _run_smoke(topology_cls, n_agents=4, max_rounds=3):
    agent_ids = [f"agent_{i}" for i in range(n_agents)]
    topology = topology_cls(agent_ids)
    router = ReinforcedRouter(beta=0.15)

    result = run_simulation(
        agent_ids=agent_ids,
        topology=topology,
        router=router,
        max_rounds=max_rounds,
        dti_enabled=False,
    )

    # Deserialize — results are dicts
    events_raw = result["events"]
    claims_raw = result["claims"]

    # Convert if they're still dicts (LangGraph may pass them through)
    claims = []
    for c in claims_raw:
        if isinstance(c, dict):
            claims.append(Claim(**c))
        else:
            claims.append(c)

    events = []
    for e in events_raw:
        if isinstance(e, dict):
            events.append(Event(**e))
        else:
            events.append(e)

    assert len(events) > 0, "No events generated"
    assert len(claims) > 0, "No claims generated"
    assert len(result["neighbor_trace"]) == n_agents * max_rounds

    # Reconstruct DAG
    dag = reconstruct_claim_dag(claims)
    assert dag.number_of_nodes() > 0

    # Extract cascades
    cascades = extract_cascades(claims, events)
    assert len(cascades) > 0

    # Compute metrics
    sizes = compute_cascade_sizes(cascades)
    assert all(s > 0 for s in sizes)

    tce_values = compute_tce(cascades)
    assert all(t >= 0 for t in tce_values)

    contributions = compute_top_k_contribution(claims, cascades, agent_ids=agent_ids)
    assert len(contributions) > 0

    return result


def test_smoke_chain():
    _run_smoke(ChainTopology)


def test_smoke_star():
    _run_smoke(StarTopology)


def test_smoke_mesh():
    _run_smoke(MeshTopology)


def test_smoke_static_exponential():
    _run_smoke(StaticExponentialTopology)


def test_smoke_one_peer_exponential():
    _run_smoke(OnePeerExponentialTopology)


def test_topology_switching_preserves_trace_and_claim_generation():
    for topology_name in topology_names():
        agent_ids = [f"agent_{i}" for i in range(5)]
        result = run_simulation(
            agent_ids=agent_ids,
            topology=create_topology(topology_name, agent_ids),
            router=ReinforcedRouter(beta=0.15),
            max_rounds=2,
            dti_enabled=False,
        )

        assert len(result["events"]) > 0
        assert len(result["claims"]) > 0
        assert len(result["neighbor_trace"]) == 10


def test_smoke_with_dti():
    from src.interventions.dti import DTIConfig, DTIMonitor

    agent_ids = [f"agent_{i}" for i in range(4)]
    topology = MeshTopology(agent_ids)

    result = run_simulation(
        agent_ids=agent_ids,
        topology=topology,
        max_rounds=5,
        dti_enabled=True,
        dti_monitor=DTIMonitor(DTIConfig(beta_c=1.5, a_c=1.0, delta_c=1.0)),
    )

    assert len(result["events"]) > 0
    assert len(result["claims"]) > 0
