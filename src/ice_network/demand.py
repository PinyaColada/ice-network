"""Seeded exogenous truth. Forecasters must never receive the latent-demand column."""

import numpy as np
import pandas as pd

from ice_network.world import BARS, Config


def season(day_of_year: np.ndarray | float) -> np.ndarray:
    return 0.60 + 0.65 * np.exp(-(((np.asarray(day_of_year) - 215) / 53) ** 2))


def climate(day_of_year: np.ndarray | float) -> np.ndarray:
    return 23 + 7 * np.exp(-(((np.asarray(day_of_year) - 215) / 48) ** 2))


def generate(config: Config) -> pd.DataFrame:
    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start, periods=config.days)
    rows = []
    anomaly = 0.0
    for day, date in enumerate(dates):
        anomaly = 0.65 * anomaly + rng.normal(0, 1.6)
        temperature = float(climate(date.dayofyear) + anomaly)
        holiday = int(date.strftime("%m-%d") in {"06-24", "08-15"})
        rain = rng.random() < 0.07
        cruise = rng.random() < 0.12
        for bar_id, bar in enumerate(BARS):
            weekend = date.dayofweek >= 5
            active = not bar.intermittent or rng.random() < (0.92 if weekend else 0.12)
            party = rng.random() < 0.025
            event = "rain" if rain else "party" if party else "cruise" if cruise else "none"
            multiplier = (0.40 if rain else 1.0) * (2.4 if party else 1.0)
            if cruise and bar_id in (0, 1, 7, 8):
                multiplier *= 1.5
            mean = (
                bar.base
                * float(season(date.dayofyear))
                * np.exp(0.045 * (temperature - 25))
                * (1.3 if weekend else 1.0)
                * (1.4 if holiday else 1.0)
                * multiplier
            )
            demand = rng.poisson(rng.gamma(14, mean / 14)) if active else 0
            rows.append(
                {
                    "day": day,
                    "date": date,
                    "bar": bar_id,
                    "temperature": temperature,
                    "holiday": holiday,
                    "event": event,
                    "latent_demand": int(demand),
                }
            )
    return pd.DataFrame(rows)
