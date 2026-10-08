"""Comparable ordering rules; every rule passes through the same physical constraints."""

from math import ceil, floor

import numpy as np
import pandas as pd

from ice_network.forecast import Forecast
from ice_network.optimize import Plan, optimize
from ice_network.simulator import Simulator
from ice_network.world import BARS, DEPOTS, melt_rate


def order(
    policy: str, sim: Simulator, observed: pd.DataFrame, forecast: Forecast | None = None
) -> Plan:
    if policy == "optimizer":
        if forecast is None:
            raise ValueError("optimizer requires a forecast")
        return optimize(sim, forecast)
    c = sim.config
    if policy == "naive":
        daily = observed[observed.day >= sim.day - 7].groupby("bar").sales.mean()
        predictions = np.tile(daily.reindex(range(len(BARS)), fill_value=0), (4, 1))
    elif policy in {"median", "quantile"} and forecast is not None:
        predictions = forecast.at(0.5 if policy == "median" else c.service)
    else:
        raise ValueError(f"unknown policy or missing forecast: {policy}")
    q = np.zeros((len(DEPOTS), len(BARS)), dtype=int)
    position = sim.position()
    production = np.array([d.production for d in DEPOTS])
    fleet = c.trucks * c.trips_per_truck
    # Serve lowest days-of-cover first, with deterministic bar-id tie breaking.
    priority = np.argsort(position / np.maximum(predictions[0], 1), kind="stable")
    for b in priority:
        for d in np.argsort(sim.km[:, b], kind="stable"):
            lead = DEPOTS[d].lead
            rate = melt_rate(float(forecast.frame.temperature.iloc[0])) if forecast else 0.04
            target = sum(predictions[h, b] / (1 - rate) ** h for h in range(lead + 1))
            desired = max(0, ceil((target - position[b]) / c.pack) * c.pack)
            room = floor((BARS[b].capacity - position[b]) / c.pack) * c.pack
            bags = min(
                desired,
                room,
                production[d] // c.pack * c.pack,
                fleet * c.truck_capacity // c.pack * c.pack,
            )
            if bags >= c.moq:
                q[d, b] = bags
                production[d] -= bags
                fleet -= ceil(bags / c.truck_capacity)
                break
    return Plan(q, "rule", 0.0, 0.0, 0.0)
