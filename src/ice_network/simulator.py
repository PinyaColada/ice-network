"""Daily ledger: morning melt → receipts → cut-off orders → demand.

Production and trips are booked on departure day. Transit has no shrinkage.
Dedicated depot/bar round trips keep routing explicit without pretending to solve a VRP.
"""

from dataclasses import dataclass
from math import ceil

import numpy as np
import pandas as pd

from ice_network.world import BARS, DEPOTS, Config, distances, melt_rate


@dataclass(frozen=True)
class Shipment:
    depot: int
    bar: int
    bags: int
    departure: int
    arrival: int
    trips: int


class Simulator:
    def __init__(self, config: Config, initial: np.ndarray | None = None) -> None:
        self.config = config
        self.inventory = np.array(
            initial if initial is not None else [b.capacity * 0.45 for b in BARS], dtype=float
        )
        self.initial = self.inventory.copy()
        self.pipeline: list[Shipment] = []
        self.shipments: list[Shipment] = []
        self.records: list[dict] = []
        self.day = -1
        self.open = False
        self.km = distances()
        self._melt = np.zeros(len(BARS))
        self._received = np.zeros(len(BARS))
        self._overflow = np.zeros(len(BARS))

    def start_day(self, day: int, temperature: float) -> None:
        if self.open or day != self.day + 1:
            raise ValueError("days must be opened and closed exactly once, in order")
        self.day, self.open = day, True
        self._melt = self.inventory * melt_rate(temperature)
        self.inventory -= self._melt
        self._received = np.zeros(len(BARS))
        for shipment in self.pipeline:
            if shipment.arrival == day:
                self._received[shipment.bar] += shipment.bags
        self.pipeline = [s for s in self.pipeline if s.arrival > day]
        self.inventory += self._received
        capacity = np.array([b.capacity for b in BARS])
        self._overflow = np.maximum(0, self.inventory - capacity)
        self.inventory = np.minimum(capacity, self.inventory)

    def position(self) -> np.ndarray:
        result = self.inventory.copy()
        for shipment in self.pipeline:
            result[shipment.bar] += shipment.bags
        return result

    def place(self, quantities: np.ndarray, hour: int = 9) -> None:
        """Atomically validate one order batch. Conservative capacity assumes no future sales."""
        c = self.config
        q = np.asarray(quantities)
        if not self.open or q.shape != (len(DEPOTS), len(BARS)):
            raise ValueError("orders require an open day and a depot × bar matrix")
        if not np.isfinite(q).all() or (q < 0).any() or (q % c.pack != 0).any():
            raise ValueError("orders must be nonnegative case-pack multiples")
        if ((q > 0) & (q < c.moq)).any():
            raise ValueError("delivery is below MOQ")
        if (self.position() + q.sum(axis=0) > np.array([b.capacity for b in BARS]) + 1e-7).any():
            raise ValueError("reserved receipts exceed storage capacity")
        departure = self.day + int(hour > c.cutoff_hour)
        reserved = [s for s in self.shipments if s.departure == departure]
        if any(
            q[d].sum() + sum(s.bags for s in reserved if s.depot == d) > dep.production
            for d, dep in enumerate(DEPOTS)
        ):
            raise ValueError("depot production exceeded")
        trips = np.ceil(q / c.truck_capacity).astype(int)
        if trips.sum() + sum(s.trips for s in reserved) > c.trucks * c.trips_per_truck:
            raise ValueError("daily fleet trip capacity exceeded")
        batch = [
            Shipment(d, b, int(q[d, b]), departure, departure + dep.lead, int(trips[d, b]))
            for d, dep in enumerate(DEPOTS)
            for b in range(len(BARS))
            if q[d, b] > 0
        ]
        self.pipeline.extend(batch)
        self.shipments.extend(batch)

    def close_day(self, truth: pd.DataFrame) -> pd.DataFrame:
        if not self.open:
            raise ValueError("start the day before serving demand")
        truth = truth.sort_values("bar")
        if truth.bar.tolist() != list(range(len(BARS))) or not (truth.day == self.day).all():
            raise ValueError("one truth row per bar for the current day is required")
        demand = truth.latent_demand.to_numpy()
        available = np.floor(self.inventory + 1e-9).astype(int)
        sales = np.minimum(demand, available)
        self.inventory -= sales
        # Sell-out is observable; whether extra customers existed is not.
        frame = truth[["day", "date", "bar", "temperature", "holiday"]].copy()
        frame["sales"] = sales
        frame["stockout"] = sales == available
        frame["available"] = available
        frame["closing"] = self.inventory
        frame["melt"] = self._melt
        frame["receipts"] = self._received
        frame["overflow"] = self._overflow
        self.records.extend(frame.to_dict("records"))
        self.open = False
        return frame

    def transport_cost(self, since: int = 0) -> float:
        c = self.config
        return sum(
            s.trips * (c.fixed_trip_cost + 2 * self.km[s.depot, s.bar] * c.km_cost)
            for s in self.shipments
            if s.departure >= since
        )


def historical_orders(sim: Simulator, day: int) -> np.ndarray:
    """An imperfect incumbent: alternate-day top-ups with deliberately modest targets."""
    q = np.zeros((len(DEPOTS), len(BARS)), dtype=int)
    if day % 2:
        return q
    position = sim.position()
    for b, bar in enumerate(BARS):
        d = int(np.argmin(sim.km[:, b]))
        desired = min(bar.capacity, bar.base * (2.0 if not bar.intermittent else 1.0))
        bags = max(0, ceil((desired - position[b]) / sim.config.pack) * sim.config.pack)
        q[d, b] = bags if bags >= sim.config.moq else 0
    return q


def history(config: Config, truth: pd.DataFrame) -> tuple[pd.DataFrame, Simulator]:
    sim = Simulator(config)
    for day, rows in truth.groupby("day", sort=True):
        sim.start_day(int(day), float(rows.temperature.iloc[0]))
        sim.place(historical_orders(sim, int(day)))
        sim.close_day(rows)
    return pd.DataFrame(sim.records), sim
