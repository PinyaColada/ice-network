import json
from dataclasses import asdict, replace

import pandas as pd
import pytest

from ice_network.backtest import replay
from ice_network.demand import generate
from ice_network.visualize import export_replay, operational_metrics, replay_data
from ice_network.world import Config


@pytest.fixture(scope="module")
def saved_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("replay")
    config = replace(Config(), days=18, warmup=14, scenarios=3)
    truth = generate(config)
    truth.to_csv(out / "truth.csv", index=False)
    (out / "config.json").write_text(json.dumps(asdict(config)))
    replay(config, truth, out)
    return out


def test_replay_payload_reconciles_with_metrics_and_preserves_missing_forecasts(saved_run):
    data = replay_data(saved_run)
    for name, run in data["runs"].items():
        rows = [dict(zip(data["fields"], r, strict=True)) for r in run["rows"]]
        lost = sum(r["latent_demand"] - r["sales"] for r in rows)
        assert lost == run["summary"]["lost_sales"]
        assert sum(r["sales"] for r in rows) / sum(r["latent_demand"] for r in rows) == (
            pytest.approx(run["summary"]["service"])
        )
        assert all((r["p50"] is None) == name.startswith("naive/") for r in rows)
        assert run["unlogged_receipts"] == 0  # Includes shared opening-pipeline deliveries.
    assert len(data["bars"]) == 12 and len(data["depots"]) == 2


def test_html_is_self_contained_and_does_not_modify_results(saved_run):
    before = {p.name: p.read_bytes() for p in saved_run.glob("*.csv")}
    document = export_replay(saved_run).read_text()
    assert "/* REPLAY_" not in document and "/* SCENE_JS */" not in document
    assert "<script src=" not in document
    assert '"latent_demand"' in document
    assert {p.name: p.read_bytes() for p in saved_run.glob("*.csv")} == before


def test_missing_backtest_has_actionable_error(tmp_path):
    with pytest.raises(ValueError, match="Run the backtest first"):
        export_replay(tmp_path)


def test_operational_costs_and_quantities_reconcile_with_backtest(saved_run):
    data = replay_data(saved_run)
    for run in data["runs"].values():
        network = run["operations"]["network"]
        summary = run["summary"]
        for metric in ("total_cost", "transport_cost", "holding_cost", "stockout_cost"):
            assert sum(r[metric] for r in network) == pytest.approx(summary[metric])
        assert sum(r["trips"] for r in network) == summary["truck_trips"]
        assert sum(r["melt"] for r in network) == pytest.approx(summary["melted_bags"])
        assert network[-1]["cumulative_fill"] == pytest.approx(summary["service"])
        for r in network:
            depot_rows = [d for d in run["operations"]["depots"] if d["day"] == r["day"]]
            assert sum(d["dispatched"] for d in depot_rows) == r["dispatched"]
            assert sum(d["in_transit"] for d in depot_rows) == r["in_transit"]
            assert all(d["dispatched"] + d["unused_capacity"] == d["capacity"] for d in depot_rows)


def test_zero_activity_and_opening_pipeline_are_not_misreported_as_efficiency():
    frame = pd.DataFrame(
        [
            dict(day=14, sales=0, latent_demand=0, closing=95, melt=5, overflow=0),
            dict(day=15, sales=40, latent_demand=50, closing=171, melt=4, overflow=0),
        ]
    )
    routes = pd.DataFrame(
        [
            dict(depot=1, bar=0, bags=40, departure=13, arrival=15, trips=1),
            dict(depot=0, bar=0, bags=80, departure=14, arrival=15, trips=1),
        ]
    )
    metrics = operational_metrics(frame, routes, asdict(Config()))
    a, b = metrics["network"]
    assert a["in_transit"] == 120 and b["in_transit"] == 0
    assert a["trips"] == 1  # Warmup departure is not billed again.
    assert a["fill_rate"] is None and a["cost_per_sold_bag"] is None
    assert a["truck_load"] == pytest.approx(80 / 360)
    assert b["truck_load"] is None and b["fleet_use"] == 0
    assert b["fill_rate"] == pytest.approx(0.8)
    assert b["ice_yield"] == pytest.approx(40 / 49)  # Closing stock is excluded.
    assert metrics["depots"][0]["unused_capacity"] == 2100 - 80
