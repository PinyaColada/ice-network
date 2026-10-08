"""Immutable world configuration. Coordinates are real; businesses are invented."""

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

import numpy as np


@dataclass(frozen=True)
class Bar:
    name: str
    lat: float
    lon: float
    capacity: int
    base: float
    intermittent: bool = False


@dataclass(frozen=True)
class Depot:
    name: str
    lat: float
    lon: float
    production: int
    lead: int


@dataclass(frozen=True)
class Config:
    seed: int = 20261008
    days: int = 153
    warmup: int = 49
    start: str = "2025-05-01"
    pack: int = 20
    moq: int = 40
    trucks: int = 6
    trips_per_truck: int = 3
    truck_capacity: int = 360
    cutoff_hour: int = 10
    fixed_trip_cost: float = 12.0
    km_cost: float = 0.32
    bag_cost: float = 1.2
    holding_cost: float = 0.015
    stockout_cost: float = 12.0
    service: float = 0.95
    retrain_every: int = 7
    scenarios: int = 9

    def __post_init__(self) -> None:
        if not 0.5 <= self.service <= 0.95:
            raise ValueError("service must be between 0.50 and 0.95 (forecast support)")
        if self.days <= self.warmup or self.warmup < 14:
            raise ValueError("need at least 14 warmup days and a nonempty evaluation period")
        if self.pack <= 0 or self.moq % self.pack or self.moq <= 0:
            raise ValueError("MOQ must be a positive case-pack multiple")


BARS = (
    Bar("Palma: Cubito Club", 39.552, 2.718, 600, 100),
    Bar("Arenal: Hielo, Luego Existo", 39.501, 2.751, 600, 105),
    Bar("Cala Pi: El Deshielo", 39.362, 2.837, 400, 48),
    Bar("Es Trenc: Bajo Cero", 39.344, 2.986, 560, 86),
    Bar("Cala d'Or: Bolsa Nostra", 39.372, 3.229, 480, 68),
    Bar("Cala Millor: Frio Fiscal", 39.601, 3.385, 560, 84),
    Bar("Cala Ratjada: Cubito Libre", 39.711, 3.464, 440, 57),
    Bar("Alcudia: La Ultima Bolsa", 39.834, 3.121, 640, 112),
    Bar("Pollenca: Stock y Playa", 39.906, 3.083, 440, 62),
    Bar("Soller: Poco a Poco", 39.797, 2.696, 320, 63, True),
    Bar("Sant Elm: Quizas Abrimos", 39.580, 2.351, 280, 57, True),
    Bar("Magaluf: Solo el Sabado", 39.506, 2.533, 360, 80, True),
)
DEPOTS = (
    Depot("Palma", 39.580, 2.650, 2100, 1),
    Depot("Alcudia", 39.853, 3.120, 1500, 2),
)


def road_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """1.3 × great-circle distance: transparent proxy, not a road routing engine."""
    a, b = radians(lat1), radians(lat2)
    h = sin((a - b) / 2) ** 2 + cos(a) * cos(b) * sin(radians(lon1 - lon2) / 2) ** 2
    return 1.3 * 6371 * 2 * asin(sqrt(h))


def distances() -> np.ndarray:
    return np.array([[road_km(d.lat, d.lon, b.lat, b.lon) for b in BARS] for d in DEPOTS])


def melt_rate(temperature: float) -> float:
    return min(0.15, 0.025 + 0.004 * max(0.0, temperature - 25))
