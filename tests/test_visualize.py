import json
from dataclasses import asdict, replace

import pytest

from ice_network.backtest import replay
from ice_network.demand import generate
from ice_network.visualize import export_replay, replay_data
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
