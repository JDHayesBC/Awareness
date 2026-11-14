"""#339: pronouns and placeholder nouns never become entities, and a fact whose
endpoint is one is dropped rather than misattributed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pps"))
from layers.entity_extractor import EntityExtractor  # noqa: E402


def _build(entities, relationships):
    return EntityExtractor()._validate_and_build(
        {"entities": entities, "relationships": relationships}, entity_name="caia")


def test_placeholders_are_not_entities():
    names = ["Entity", "Entities", "Her", "him", "HIS", "Them", "Men", "herself"]
    ents, _ = _build([{"name": n, "type": "Person"} for n in names], [])
    assert ents == []


def test_real_names_still_pass():
    ents, _ = _build([{"name": "Lyra", "type": "Person"},
                      {"name": "Jeff", "type": "Person"},
                      {"name": "IT", "type": "Concept"}], [])
    assert [e.name for e in ents] == ["Lyra", "Jeff", "IT"]


def test_fact_with_placeholder_endpoint_is_dropped():
    ents = [{"name": "Jeff", "type": "Person"}, {"name": "Lyra", "type": "Person"}]
    rels = [
        {"source": "Jeff", "target": "Entity", "type": "Trusts", "fact": "Jeff trusts Entity."},
        {"source": "her", "target": "Jeff", "type": "Loves", "fact": "She loves Jeff."},
        {"source": "Jeff", "target": "Lyra", "type": "Loves", "fact": "Jeff loves Lyra."},
    ]
    _, out = _build(ents, rels)
    assert [(r.source_name, r.target_name) for r in out] == [("Jeff", "Lyra")]
