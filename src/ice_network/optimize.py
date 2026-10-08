"""Small scenario MILP, solved by SCIP. No full vehicle-routing problem is implied.

Each route is a dedicated depot→bar→depot trip. Integer route counts can be assigned
to identical trucks with at most three trips each; travel time is not modeled.
"""

from dataclasses import dataclass

import numpy as np
from pyscipopt import Model, quicksum

from ice_network.forecast import Forecast
from ice_network.simulator import Simulator
from ice_network.world import BARS, DEPOTS, melt_rate


@dataclass
class Plan:
    quantities: np.ndarray
    status: str
    gap: float
    service_slack: float
    objective: float


def optimize(sim: Simulator, forecast: Forecast, hour: int = 9) -> Plan:
    c = sim.config
    samples = forecast.scenarios(c.scenarios, c.seed + sim.day)
    n, horizon, bars = samples.shape
    delay = int(hour > c.cutoff_hour)
    departure = sim.day + delay
    if horizon <= max(d.lead for d in DEPOTS) + delay:
        raise ValueError("forecast horizon must cover all arrival dates")
    booked = [s for s in sim.shipments if s.departure == departure]
    receipts = np.zeros((horizon, bars))
    for shipment in sim.pipeline:
        h = shipment.arrival - sim.day
        if 0 <= h < horizon:
            receipts[h, shipment.bar] += shipment.bags
    weather = forecast.frame.groupby("day", sort=True).temperature.first().to_numpy()
    rates = [melt_rate(float(t)) for t in weather]
    model = Model("ice-network")
    model.hideOutput()
    model.setIntParam("parallel/maxnthreads", 1)
    model.setIntParam("randomization/randomseedshift", c.seed % 2147483647)
    # A deterministic work limit supports repeatability better than a wall-clock timeout.
    model.setLongintParam("limits/nodes", 2000)
    model.setRealParam("limits/gap", 0.01)
    packs, trips, costs = {}, {}, []
    for d, depot in enumerate(DEPOTS):
        for b, bar in enumerate(BARS):
            packs[d, b] = model.addVar(vtype="INTEGER", lb=0, ub=bar.capacity // c.pack)
            delivery = model.addVar(vtype="BINARY")
            trips[d, b] = model.addVar(vtype="INTEGER", lb=0, ub=c.trucks * c.trips_per_truck)
            q = c.pack * packs[d, b]
            model.addCons(q >= c.moq * delivery)
            model.addCons(q <= bar.capacity * delivery)
            model.addCons(q <= c.truck_capacity * trips[d, b])
            model.addCons(trips[d, b] <= c.trucks * c.trips_per_truck * delivery)
            costs.append(trips[d, b] * (c.fixed_trip_cost + 2 * sim.km[d, b] * c.km_cost))
        model.addCons(
            c.pack * quicksum(packs[d, b] for b in range(bars))
            <= depot.production - sum(s.bags for s in booked if s.depot == d)
        )
    model.addCons(
        quicksum(trips.values()) <= c.trucks * c.trips_per_truck - sum(s.trips for s in booked)
    )
    position = sim.position()
    for b, bar in enumerate(BARS):
        # Hard storage guarantee even with zero demand and zero future melting.
        model.addCons(
            c.pack * quicksum(packs[d, b] for d in range(len(DEPOTS)))
            <= max(0, bar.capacity - position[b])
        )

    losses = []
    controllable_demand = 0.0
    for s in range(n):
        for b, bar in enumerate(BARS):
            previous = float(sim.inventory[b])
            for h in range(horizon):
                closing = model.addVar(lb=0, ub=bar.capacity)
                lost = model.addVar(lb=0, ub=float(samples[s, h, b]))
                stocked = model.addVar(vtype="BINARY")
                # Complementarity prevents invented inventory via simultaneous loss and stock.
                model.addCons(closing <= bar.capacity * stocked)
                model.addCons(lost <= float(samples[s, h, b]) * (1 - stocked))
                melt = 0 if h == 0 else previous * rates[h]
                arrival = receipts[h, b] + c.pack * quicksum(
                    packs[d, b] for d, depot in enumerate(DEPOTS) if depot.lead + delay == h
                )
                model.addCons(closing - lost == previous - melt + arrival - samples[s, h, b])
                costs.extend(
                    [(c.holding_cost * closing + c.bag_cost * melt + c.stockout_cost * lost) / n]
                )
                if h >= min(d.lead for d in DEPOTS) + delay:
                    losses.append(lost / n)
                    controllable_demand += samples[s, h, b] / n
                previous = closing
    slack = model.addVar(lb=0)
    model.addCons(quicksum(losses) <= (1 - c.service) * controllable_demand + slack)
    # Explicit soft service constraint: fleet/storage may make a hard target infeasible.
    model.setObjective(quicksum(costs) + 2 * c.stockout_cost * slack, "minimize")
    model.optimize()
    if model.getNSols() == 0:
        raise RuntimeError(f"SCIP returned no feasible incumbent: {model.getStatus()}")
    quantities = np.array(
        [
            [c.pack * round(model.getVal(packs[d, b])) for b in range(bars)]
            for d in range(len(DEPOTS))
        ],
        dtype=int,
    )
    return Plan(
        quantities,
        str(model.getStatus()),
        float(model.getGap()),
        float(model.getVal(slack)),
        float(model.getObjVal()),
    )
