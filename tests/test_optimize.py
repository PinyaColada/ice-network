from dataclasses import replace

import numpy as np
import pytest

from ice_network.demand import generate
from ice_network.forecast import Forecast, future_frame
from ice_network.optimize import optimize
from ice_network.simulator import Simulator
from ice_network.world import BARS, DEPOTS, Config


def test_milp_feasible_under_tight_fleet_and_high_demand() -> None:
    c = replace(Config(), trucks=1, trips_per_truck=2, scenarios=3)
    sim = Simulator(c, np.zeros(len(BARS)))
    sim.start_day(0, 33)
    forecast = Forecast(future_frame(0, 33, c), np.tile([90, 160, 260, 300], (48, 1)))
    plan = optimize(sim, forecast)
    q = plan.quantities
    assert q.sum() > 0
    assert (q % c.pack == 0).all()
    assert ((q == 0) | (q >= c.moq)).all()
    assert np.ceil(q / c.truck_capacity).sum() <= 2
    assert (q.sum(axis=0) <= [b.capacity for b in BARS]).all()
    assert (q.sum(axis=1) <= [d.production for d in DEPOTS]).all()
    assert plan.service_slack > 0
    sim.place(q)  # Independent operational validator, not just solver status.


def test_no_free_early_arrivals_and_conservation_after_milp() -> None:
    c = replace(Config(), scenarios=3)
    sim = Simulator(c, np.zeros(len(BARS)))
    sim.start_day(0, 30)
    f = Forecast(future_frame(0, 30, c), np.tile([40, 60, 100, 120], (48, 1)))
    plan = optimize(sim, f, hour=11)
    sim.place(plan.quantities, hour=11)
    assert all(s.departure == 1 and s.arrival == 1 + DEPOTS[s.depot].lead for s in sim.pipeline)
    truth = generate(c)
    result = sim.close_day(truth[truth.day == 0])
    assert result.sales.sum() == 0
    for day in range(1, 5):
        rows = truth[truth.day == day]
        sim.start_day(day, float(rows.temperature.iloc[0]))
        sim.close_day(rows)
    assert sum(s.bags for s in sim.shipments) == pytest.approx(
        sum(r["sales"] + r["melt"] + r["overflow"] for r in sim.records)
        + sim.inventory.sum()
        + sum(s.bags for s in sim.pipeline)
    )
