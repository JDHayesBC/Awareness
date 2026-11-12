"""graph_merge never collapses parallel edges (#337).

Runs against the live Neo4j, inside a scratch group_id that no entity uses,
and deletes only that group afterwards. Skips if Neo4j is unreachable.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import graph_merge as gm  # noqa: E402

neo4j = pytest.importorskip("neo4j")
GID = "test_graph_merge_scratch"


@pytest.fixture
def driver():
    try:
        d = neo4j.GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password123"))
        d.verify_connectivity()
    except Exception:
        pytest.skip("Neo4j not reachable")
    _wipe(d)
    yield d
    _wipe(d)
    d.close()


def _wipe(d):
    d.execute_query("MATCH (e:Entity {group_id: $gid}) DETACH DELETE e", gid=GID)


def _seed(d, parallel=3):
    """Alias with `parallel` same-type edges to one neighbor (the landmine shape),
    one incoming edge, and a canonical that already has its own edge to that neighbor."""
    d.execute_query(
        """
        CREATE (a:Entity {group_id:$gid, name:'Alias'}),
               (c:Entity {group_id:$gid, name:'Canon'}),
               (x:Entity {group_id:$gid, name:'X'}),
               (y:Entity {group_id:$gid, name:'Y'}),
               (c)-[:RELATES_TO {group_id:$gid, fact:'canon fact', uuid:'c0'}]->(x),
               (y)-[:RELATES_TO {group_id:$gid, fact:'incoming', uuid:'in1'}]->(a)
        WITH a, x
        UNWIND range(1, $n) AS i
        CREATE (a)-[:RELATES_TO {group_id:$gid, fact:'episode ' + toString(i), uuid:'a' + toString(i)}]->(x)
        """,
        gid=GID, n=parallel,
    )


def _facts(d, name):
    recs, _, _ = d.execute_query(
        "MATCH (e:Entity {group_id:$gid, name:$n})-[r]-() RETURN r.fact AS f ORDER BY f",
        gid=GID, n=name,
    )
    return [r["f"] for r in recs]


def test_dry_run_writes_nothing(driver):
    _seed(driver)
    plan = gm.merge_alias(driver, GID, "Alias", "Canon", rewire=True)
    assert not plan.applied
    assert plan.alias_edges == 4
    assert _facts(driver, "Alias") != []
    assert len(_facts(driver, "Canon")) == 1


def test_refuses_edges_without_rewire(driver):
    _seed(driver)
    with pytest.raises(gm.MergeRefused):
        gm.merge_alias(driver, GID, "Alias", "Canon", note="t", apply=True)
    assert len(_facts(driver, "Alias")) == 4


def test_rewire_keeps_every_parallel_edge(driver):
    _seed(driver, parallel=3)
    plan = gm.merge_alias(driver, GID, "Alias", "Canon", rewire=True, note="t-note", apply=True)
    assert plan.applied
    assert plan.canonical_edges_after == 1 + 4
    facts = _facts(driver, "Canon")
    assert facts == sorted(["canon fact", "episode 1", "episode 2", "episode 3", "incoming"])
    recs, _, _ = driver.execute_query(
        "MATCH (e:Entity {group_id:$gid, name:'Alias'}) RETURN count(e) AS n", gid=GID)
    assert recs[0]["n"] == 0
    # direction and provenance survive
    recs, _, _ = driver.execute_query(
        "MATCH (:Entity {group_id:$gid, name:'Y'})-[r]->(:Entity {group_id:$gid, name:'Canon'}) "
        "RETURN r.uuid AS u, r.curation_note AS n", gid=GID)
    assert [(r["u"], r["n"]) for r in recs] == [("in1", "t-note")]


def test_zero_edge_alias_is_just_deleted(driver):
    driver.execute_query(
        "CREATE (:Entity {group_id:$gid, name:'Alias'}), (:Entity {group_id:$gid, name:'Canon'})",
        gid=GID)
    plan = gm.merge_alias(driver, GID, "Alias", "Canon", note="t", apply=True)
    assert plan.applied and plan.alias_edges == 0


def test_refuses_edge_between_alias_and_canonical(driver):
    _seed(driver)
    driver.execute_query(
        "MATCH (a:Entity {group_id:$gid, name:'Alias'}), (c:Entity {group_id:$gid, name:'Canon'}) "
        "CREATE (a)-[:RELATES_TO {group_id:$gid, fact:'between'}]->(c)", gid=GID)
    with pytest.raises(gm.MergeRefused, match="self-loops"):
        gm.merge_alias(driver, GID, "Alias", "Canon", rewire=True, note="t", apply=True)


def test_group_scoping_refuses_names_from_another_group(driver):
    _seed(driver)
    with pytest.raises(gm.MergeRefused, match="exactly one"):
        gm.merge_alias(driver, GID, "Alias", "Jeff", rewire=True, note="t", apply=True)


def test_apply_requires_note(driver):
    _seed(driver)
    with pytest.raises(gm.MergeRefused, match="note"):
        gm.merge_alias(driver, GID, "Alias", "Canon", rewire=True, apply=True)
