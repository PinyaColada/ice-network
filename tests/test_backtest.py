from dataclasses import replace

import pandas as pd
import pytest

from ice_network.backtest import replay, verdict
from ice_network.demand import generate
from ice_network.forecast import Forecaster
from ice_network.world import Config


def test_replay_uses_only_past_sales_and_accounts_for_all_costs(tmp_path, monkeypatch) -> None:
    original = Forecaster.fit
    seen = []

    def guarded_fit(self, observed):
        assert "latent_demand" not in observed
        assert observed.day.max() == 13  # All later observations must still be in the future.
        seen.append(self.name)
        return original(self, observed)

    monkeypatch.setattr(Forecaster, "fit", guarded_fit)
    c = replace(Config(), days=18, warmup=14, scenarios=3)
    result = replay(c, generate(c), tmp_path)
    assert len(result) == 7 and len(seen) == 6
    assert result.conservation_error.abs().max() < 1e-6
    assert result.overflow_bags.sum() == 0
    assert result.ending_pipeline.sum() == 0
    components = [
        "transport_cost",
        "holding_cost",
        "melting_cost",
        "overflow_cost",
        "stockout_cost",
    ]
    assert result.total_cost.to_numpy() == pytest.approx(result[components].sum(axis=1).to_numpy())
    assert result.service.between(0, 1).all()


def test_verdict_does_not_claim_reversal_when_nobody_qualifies() -> None:
    metrics = pd.DataFrame({"horizon": [1, 1], "model": ["seasonal", "hurdle"], "mae": [10, 12]})
    policies = pd.DataFrame(
        {
            "policy": ["optimizer"] * 2,
            "model": ["seasonal", "hurdle"],
            "service": [0.90, 0.94],
            "total_cost": [100, 90],
        }
    )
    assert not verdict(metrics, policies, 0.95)["reversal_observed"]
    policies.loc[1, "service"] = 0.96
    assert verdict(metrics, policies, 0.95)["reversal_observed"]
