"""Curation pressure counts only curatable work and doesn't let one term mask the other (#345, #336)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layers.custom_graph import CustomGraphLayer  # noqa: E402


class _Rec:
    def __init__(self, d):
        self._d = d

    def data(self):
        return self._d


class _Driver:
    def __init__(self, row):
        self.row = row
        self.cypher = None

    def execute_query(self, cypher, **kw):
        self.cypher = cypher
        return [_Rec(self.row)], None, None


def _layer(row):
    layer = CustomGraphLayer.__new__(CustomGraphLayer)
    layer._group_id = "test"
    drv = _Driver(row)
    layer._get_driver = lambda: drv
    return layer, drv


def test_terms_are_summed_not_maxed():
    last = datetime.now(timezone.utc) - timedelta(days=14)
    layer, _ = _layer({"uncurated_count": 300, "last_curated": last})
    pressure, count, days = layer.get_curation_pressure()
    assert count == 300
    assert days == pytest.approx(14.0, abs=0.01)
    # max() would give 3.0 and hide the 14 days; the sum shows both.
    assert pressure == pytest.approx(4.0, abs=0.01)


def test_neglect_surfaces_with_small_backlog():
    last = datetime.now(timezone.utc) - timedelta(days=21)
    layer, _ = _layer({"uncurated_count": 10, "last_curated": last})
    pressure, _, _ = layer.get_curation_pressure()
    assert pressure >= 1.5


def test_clean_graph_reads_quiet():
    layer, _ = _layer({"uncurated_count": 0, "last_curated": datetime.now(timezone.utc)})
    pressure, _, _ = layer.get_curation_pressure()
    assert pressure < 0.01


def test_query_excludes_floor_tech_and_tech_singletons():
    layer, drv = _layer({"uncurated_count": 0, "last_curated": None})
    layer.get_curation_pressure()
    q = " ".join(drv.cypher.split())
    assert "duration('P4D')" in q
    assert "NOT (tech AND fresh)" in q
    assert "NOT (tech AND mentions <= 1)" in q


def test_never_curated_is_loud():
    layer, _ = _layer({"uncurated_count": 0, "last_curated": None})
    pressure, _, days = layer.get_curation_pressure()
    assert days == 999.0
    assert pressure > 2.0
