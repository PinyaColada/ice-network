import numpy as np
import pandas as pd
import pytest

from ice_network.demand import generate
from ice_network.simulator import Simulator, history
from ice_network.world import BARS, Config


def test_seeded_demand_and_censoring() -> None:
    c = Config(days=60)
    truth = generate(c)
    pd.testing.assert_frame_equal(truth, generate(c))
    observed, _ = history(c, truth)
    assert "latent_demand" not in observed
    assert (observed.sales <= truth.latent_demand).all()
    assert (observed.sales <= observed.available).all()
    assert (observed.sales < truth.latent_demand).any()
    assert truth[truth.bar == 10].latent_demand.eq(0).mean() > 0.3


def test_ice_conservation_including_pipeline() -> None:
    c = Config(days=60)
    observed, sim = history(c, generate(c))
    for b in range(len(BARS)):
        ledger = observed[observed.bar == b]
        ordered = sum(s.bags for s in sim.shipments if s.bar == b)
        transit = sum(s.bags for s in sim.pipeline if s.bar == b)
        assert sim.initial[b] + ordered == pytest.approx(
            ledger.sales.sum()
            + ledger["melt"].sum()
            + ledger.overflow.sum()
            + sim.inventory[b]
            + transit
        )
    assert observed.overflow.sum() == 0


def test_cutoff_lead_time_and_atomic_rejection() -> None:
    sim = Simulator(Config(), np.zeros(len(BARS)))
    sim.start_day(0, 25)
    q = np.zeros((2, len(BARS)), dtype=int)
    q[0, 0], q[1, 1] = 40, 40
    sim.place(q, hour=11)
    assert [(s.departure, s.arrival) for s in sim.pipeline] == [(1, 2), (1, 3)]
    before = sim.pipeline.copy()
    q[0, 0] = 41
    with pytest.raises(ValueError, match="case-pack"):
        sim.place(q)
    assert sim.pipeline == before
