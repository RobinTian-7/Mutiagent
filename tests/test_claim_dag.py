"""Tests for Claim DAG reconstruction."""

from src.schemas.claims import Claim, ClaimType
from src.reconstruction.claim_dag import reconstruct_claim_dag


def _make_claims() -> list[Claim]:
    """Create the worked example from Appendix B.6.

    Paper: c1 (root) → c2 (revision), c3 (contradiction)
           c2 → c4 (revision)
           c2, c3, c4 → c5 (merge)
    """
    return [
        Claim(claim_id="c1", agent_id="a0", root_claim_id="c1",
              claim_type=ClaimType.PROPOSED),
        Claim(claim_id="c2", agent_id="a1", root_claim_id="c1",
              parent_claim_ids=["c1"], claim_type=ClaimType.REVISED, claim_depth=1),
        Claim(claim_id="c3", agent_id="a2", root_claim_id="c1",
              parent_claim_ids=["c1"], claim_type=ClaimType.CONTRADICTORY, claim_depth=1),
        Claim(claim_id="c4", agent_id="a1", root_claim_id="c1",
              parent_claim_ids=["c2"], claim_type=ClaimType.REVISED, claim_depth=2),
        Claim(claim_id="c5", agent_id="a3", root_claim_id="c1",
              parent_claim_ids=["c2", "c3", "c4"], claim_type=ClaimType.MERGED, claim_depth=3),
    ]


def test_dag_has_correct_nodes():
    dag = reconstruct_claim_dag(_make_claims())
    assert set(dag.nodes) == {"c1", "c2", "c3", "c4", "c5"}


def test_dag_has_correct_edges():
    dag = reconstruct_claim_dag(_make_claims())
    expected_edges = {
        ("c1", "c2"), ("c1", "c3"),
        ("c2", "c4"),
        ("c2", "c5"), ("c3", "c5"), ("c4", "c5"),
    }
    assert set(dag.edges) == expected_edges


def test_dag_is_acyclic():
    dag = reconstruct_claim_dag(_make_claims())
    import networkx as nx
    assert nx.is_directed_acyclic_graph(dag)


def test_root_has_no_incoming_edges():
    dag = reconstruct_claim_dag(_make_claims())
    assert dag.in_degree("c1") == 0


def test_merge_node_has_multiple_parents():
    dag = reconstruct_claim_dag(_make_claims())
    assert dag.in_degree("c5") == 3
