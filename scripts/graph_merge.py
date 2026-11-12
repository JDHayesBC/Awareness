#!/usr/bin/env python3
"""Safe alias -> canonical node merge for the custom knowledge graph (#337).

There is deliberately no APOC here. ``apoc.refactor.mergeNodes`` with
``mergeRels:true`` collapses every parallel same-(type, endpoint) edge on the
survivor down to one. Our pipeline keeps one edge per episode on purpose
(provenance lives in each edge's ``fact``), and on 2026-07-21 that flag took
the Crusher node from 89 edges to 20 and flattened Jeff's neighborhood. This
module has no flag that could reach that path.

What it does instead is the hand-rewire the /curate skill describes:

1. Both nodes must exist, exactly once each, in the given ``group_id``.
2. A zero-edge alias is simply deleted. This is the low-risk default.
3. An alias with edges is refused unless ``rewire=True``. With it, each
   ``(alias)-[r]-(x)`` is recreated on the canonical with the same type,
   direction and every property, plus a ``curation_note``. The alias is then
   deleted. Nothing is collapsed, so N edges in gives N edges out.
4. An edge directly between alias and canonical would become a self-loop, so
   the merge refuses and leaves the call to the curator.
5. It all runs in one transaction. If the canonical didn't gain exactly the
   alias's edge count, it raises and rolls back.

Dry-run is the default. Pass ``--apply`` to write.

    pps/venv/bin/python3 scripts/graph_merge.py --group caia \\
        --alias "The Chenille" --canonical "Beige Chenille Throw" \\
        --rewire --note caia-curate-2026-11-12 [--apply]
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class MergeRefused(Exception):
    """The merge was refused before anything was written."""


@dataclass
class MergePlan:
    group_id: str
    alias: str
    canonical: str
    alias_edges: int = 0
    canonical_edges_before: int = 0
    edges_by_type: dict = field(default_factory=dict)
    applied: bool = False
    canonical_edges_after: int | None = None

    def describe(self) -> str:
        mode = "APPLIED" if self.applied else "DRY RUN"
        lines = [
            f"[{mode}] group={self.group_id}: '{self.alias}' -> '{self.canonical}'",
            f"  alias edges: {self.alias_edges} {self.edges_by_type or ''}".rstrip(),
            f"  canonical edges before: {self.canonical_edges_before}",
        ]
        if self.applied:
            lines.append(f"  canonical edges after: {self.canonical_edges_after}")
        else:
            lines.append(
                f"  canonical edges after (expected): "
                f"{self.canonical_edges_before + self.alias_edges}"
            )
        return "\n".join(lines)


def _one_node(tx, group_id: str, name: str):
    rows = list(tx.run(
        "MATCH (e:Entity {group_id: $gid, name: $name}) RETURN elementId(e) AS id",
        gid=group_id, name=name,
    ))
    if len(rows) != 1:
        raise MergeRefused(
            f"expected exactly one Entity named {name!r} in group {group_id!r}, "
            f"found {len(rows)}"
        )
    return rows[0]["id"]


def _degree(tx, node_id) -> int:
    return tx.run(
        "MATCH (e) WHERE elementId(e) = $id OPTIONAL MATCH (e)-[r]-() RETURN count(r) AS c",
        id=node_id,
    ).single()["c"]


def _merge_tx(tx, plan: MergePlan, rewire: bool, note: str, apply: bool):
    alias_id = _one_node(tx, plan.group_id, plan.alias)
    canon_id = _one_node(tx, plan.group_id, plan.canonical)
    if alias_id == canon_id:
        raise MergeRefused("alias and canonical are the same node")

    plan.alias_edges = _degree(tx, alias_id)
    plan.canonical_edges_before = _degree(tx, canon_id)
    for row in tx.run(
        "MATCH (a)-[r]-() WHERE elementId(a) = $id RETURN type(r) AS t, count(r) AS c",
        id=alias_id,
    ):
        plan.edges_by_type[row["t"]] = row["c"]

    between = tx.run(
        "MATCH (a)-[r]-(c) WHERE elementId(a) = $a AND elementId(c) = $c RETURN count(r) AS n",
        a=alias_id, c=canon_id,
    ).single()["n"]
    if between:
        raise MergeRefused(
            f"{between} edge(s) run directly between alias and canonical; "
            "they would become self-loops. Delete or keep them by hand first."
        )
    loops = tx.run(
        "MATCH (a)-[r]->(a) WHERE elementId(a) = $a RETURN count(r) AS n", a=alias_id,
    ).single()["n"]
    if loops:
        raise MergeRefused(f"alias has {loops} self-loop edge(s); resolve them by hand first")
    if plan.alias_edges and not rewire:
        raise MergeRefused(
            f"alias has {plan.alias_edges} edge(s); pass rewire=True (--rewire) "
            "to move them onto the canonical one by one"
        )
    for t in plan.edges_by_type:
        if not _TYPE_RE.match(t):
            raise MergeRefused(f"unexpected relationship type {t!r}")

    if not apply:
        return

    for t in plan.edges_by_type:
        # Outgoing from alias: (alias)-[r]->(x)  =>  (canonical)-[r2]->(x)
        tx.run(
            f"""
            MATCH (a)-[r:{t}]->(x), (c)
            WHERE elementId(a) = $a AND elementId(c) = $c
            CREATE (c)-[r2:{t}]->(x)
            SET r2 = properties(r), r2.curation_note = $note
            """,
            a=alias_id, c=canon_id, note=note,
        )
        # Incoming to alias: (x)-[r]->(alias)  =>  (x)-[r2]->(canonical)
        tx.run(
            f"""
            MATCH (x)-[r:{t}]->(a), (c)
            WHERE elementId(a) = $a AND elementId(c) = $c
            CREATE (x)-[r2:{t}]->(c)
            SET r2 = properties(r), r2.curation_note = $note
            """,
            a=alias_id, c=canon_id, note=note,
        )

    after = _degree(tx, canon_id)
    expected = plan.canonical_edges_before + plan.alias_edges
    if after != expected:
        raise RuntimeError(
            f"edge count check failed: canonical has {after}, expected {expected}; "
            "rolling back"
        )
    tx.run("MATCH (a) WHERE elementId(a) = $a DETACH DELETE a", a=alias_id)
    plan.canonical_edges_after = after
    plan.applied = True


def merge_alias(driver, group_id: str, alias: str, canonical: str, *,
                rewire: bool = False, note: str = "", apply: bool = False) -> MergePlan:
    """Merge ``alias`` into ``canonical`` within ``group_id``. Dry-run unless ``apply``."""
    if not group_id:
        raise MergeRefused("group_id is required")
    if apply and not note:
        raise MergeRefused("a curation note is required when applying")
    plan = MergePlan(group_id=group_id, alias=alias, canonical=canonical)
    with driver.session() as session:
        session.execute_write(_merge_tx, plan, rewire, note, apply)
    return plan


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--group", required=True, help="group_id, e.g. caia or lyra_v2")
    p.add_argument("--alias", required=True)
    p.add_argument("--canonical", required=True)
    p.add_argument("--rewire", action="store_true",
                   help="move the alias's edges onto the canonical (never collapses them)")
    p.add_argument("--note", default="", help="curation_note stamped on moved edges")
    p.add_argument("--apply", action="store_true", help="write; otherwise dry-run")
    p.add_argument("--uri", default="bolt://localhost:7687")
    p.add_argument("--user", default="neo4j")
    p.add_argument("--password", default="password123")
    a = p.parse_args(argv)

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(a.uri, auth=(a.user, a.password))
    try:
        plan = merge_alias(driver, a.group, a.alias, a.canonical,
                           rewire=a.rewire, note=a.note, apply=a.apply)
    except MergeRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    finally:
        driver.close()
    print(plan.describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
