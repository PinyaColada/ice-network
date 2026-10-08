"""Past-only reconstruction and two probabilistic forecasters.

No model accepts latent demand. Intermittency is an empirical mass at zero in the
seasonal model and an explicit occurrence/positive-size hurdle in the boosted model.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from ice_network.demand import climate, season
from ice_network.world import BARS, Config

LEVELS = np.array([0.10, 0.50, 0.90, 0.95])
POSITIVE_LEVELS = np.array([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])


def scale(frame: pd.DataFrame) -> np.ndarray:
    """Prespecified calendar/temperature normalization, shared by both candidates."""
    return season(pd.to_datetime(frame.date).dt.dayofyear.to_numpy()) * np.exp(
        0.045 * (frame.temperature.to_numpy() - 25)
    )


def reconstruct(observed: pd.DataFrame) -> pd.DataFrame:
    """Replace sell-outs by a lower-bounded mean of earlier, uncensored similar days.

    Match bar and weekend status, then use the nearest eight temperatures in 56 days.
    Normalize donors for season and heat. No donors: retain the observed lower bound.
    This is an approximation: uncensored donors have selection bias, especially in tails.
    """
    if "latent_demand" in observed:
        raise ValueError("latent demand is evaluator-only")
    frame = observed.sort_values(["day", "bar"]).reset_index(drop=True).copy()
    norm = scale(frame)
    weekend = pd.to_datetime(frame.date).dt.dayofweek.to_numpy() >= 5
    y = frame.sales.to_numpy(dtype=float).copy()
    for i in np.flatnonzero(frame.stockout.to_numpy()):
        row = frame.iloc[i]
        mask = (
            (frame.bar.to_numpy() == row.bar)
            & (frame.day.to_numpy() < row.day)
            & (frame.day.to_numpy() >= row.day - 56)
            & ~frame.stockout.to_numpy()
            & (weekend == weekend[i])
        )
        donors = np.flatnonzero(mask)
        if donors.size:
            nearest = donors[
                np.argsort(
                    np.abs(frame.temperature.to_numpy()[donors] - row.temperature), kind="stable"
                )[:8]
            ]
            y[i] = max(y[i], float(np.mean(y[nearest] / norm[nearest]) * norm[i]))
    frame["reconstructed"] = y
    return frame


def future_frame(day: int, temperature: float, config: Config, horizon: int = 4) -> pd.DataFrame:
    """Issuance-time weather proxy: current morning anomaly decays toward climatology."""
    today = pd.Timestamp(config.start) + pd.Timedelta(days=day)
    anomaly = temperature - float(climate(today.dayofyear))
    rows = []
    for h in range(horizon):
        date = today + pd.Timedelta(days=h)
        for b in range(len(BARS)):
            rows.append(
                {
                    "day": day + h,
                    "date": date,
                    "bar": b,
                    "temperature": float(climate(date.dayofyear)) + anomaly * 0.65**h,
                    "holiday": int(date.strftime("%m-%d") in {"06-24", "08-15"}),
                }
            )
    return pd.DataFrame(rows)


def features(frame: pd.DataFrame) -> np.ndarray:
    dates = pd.to_datetime(frame.date)
    return np.column_stack(
        [
            np.eye(len(BARS))[frame.bar.to_numpy(dtype=int)],
            dates.dt.dayofweek.to_numpy(),
            frame.temperature.to_numpy(),
            season(dates.dt.dayofyear.to_numpy()),
            frame.holiday.to_numpy(),
        ]
    )


@dataclass
class Forecast:
    frame: pd.DataFrame
    values: np.ndarray

    def at(self, quantile: float) -> np.ndarray:
        """Horizon × bar matrix, linearly interpolated within the published quantiles."""
        if not LEVELS[0] <= quantile <= LEVELS[-1]:
            raise ValueError("quantile is outside forecast support")
        return np.array([np.interp(quantile, LEVELS, row) for row in self.values]).reshape(
            -1, len(BARS)
        )

    def scenarios(self, count: int, seed: int) -> np.ndarray:
        """Stratified marginal draws, independent across bar/days; bounded tail extrapolation.

        Dependence and demand above the extrapolated P100 remain explicit limitations.
        """
        rng = np.random.default_rng(seed)
        values = []
        for row in self.values:
            u = (np.arange(count) + 0.5) / count
            rng.shuffle(u)
            tail = row[-1] + max(row[-1] - row[-2], 0.1 * row[-1])
            values.append(np.interp(u, [0, *LEVELS, 1], [0, *row, tail]))
        return np.array(values).T.reshape(count, -1, len(BARS))


class Forecaster:
    def __init__(self, name: str, seed: int = 20261008) -> None:
        if name not in {"seasonal", "hurdle"}:
            raise ValueError(name)
        self.name, self.seed = name, seed
        self.training: pd.DataFrame | None = None
        self.classifier: HistGradientBoostingClassifier | None = None
        self.regressors: list[HistGradientBoostingRegressor] = []
        self.probability = 1.0
        self.last_day = -1

    def fit(self, observed: pd.DataFrame) -> "Forecaster":
        self.training = reconstruct(observed)
        self.last_day = int(self.training.day.max())
        if self.name == "seasonal":
            return self
        x = features(self.training)
        y = self.training.reconstructed.to_numpy() / scale(self.training)
        active = y > 0
        self.probability = float(active.mean())
        self.classifier = None
        params = dict(
            max_iter=65,
            max_leaf_nodes=12,
            min_samples_leaf=15,
            l2_regularization=3.0,
            random_state=self.seed,
            early_stopping=False,
        )
        with threadpool_limits(limits=1):
            if np.unique(active).size == 2:
                self.classifier = HistGradientBoostingClassifier(**params).fit(x, active)
            self.regressors = (
                [
                    HistGradientBoostingRegressor(loss="quantile", quantile=float(q), **params).fit(
                        x[active], y[active]
                    )
                    for q in POSITIVE_LEVELS
                ]
                if active.any()
                else []
            )
        return self

    def predict(self, future: pd.DataFrame) -> Forecast:
        if self.training is None or future.day.min() <= self.last_day:
            raise ValueError("fit on strictly earlier observations before predicting")
        norms = scale(future)
        if self.name == "seasonal":
            train = self.training
            weekend = pd.to_datetime(train.date).dt.dayofweek >= 5
            normalized = train.reconstructed.to_numpy() / scale(train)
            rows = []
            for i, row in enumerate(future.itertuples()):
                mask = (
                    (train.bar == row.bar)
                    & (weekend == (row.date.dayofweek >= 5))
                    & (train.day > self.last_day - 56)
                ).to_numpy()
                donors = normalized[mask]
                if not len(donors):
                    donors = normalized[(train.bar == row.bar).to_numpy()]
                # The empirical distribution equals a group mean plus its residual quantiles.
                rows.append(np.quantile(donors, LEVELS) * norms[i])
            values = np.array(rows)
        else:
            x = features(future)
            with threadpool_limits(limits=1):
                p = (
                    self.classifier.predict_proba(x)[:, 1]
                    if self.classifier is not None
                    else np.full(len(x), self.probability)
                )
                positive = (
                    np.maximum(
                        0,
                        np.sort(
                            np.column_stack([reg.predict(x) for reg in self.regressors]), axis=1
                        ),
                    )
                    if self.regressors
                    else np.zeros((len(x), len(POSITIVE_LEVELS)))
                )
            values = (
                np.array(
                    [
                        [
                            0
                            if q <= 1 - probability
                            else np.interp(
                                (q - 1 + probability) / max(probability, 1e-9),
                                POSITIVE_LEVELS,
                                sizes,
                            )
                            for q in LEVELS
                        ]
                        for probability, sizes in zip(p, positive, strict=True)
                    ]
                )
                * norms[:, None]
            )
        return Forecast(future.copy(), np.maximum.accumulate(np.maximum(0, values), axis=1))


def scores(actual: np.ndarray, quantiles: np.ndarray) -> dict[str, float]:
    error = actual[:, None] - quantiles
    pinball = np.maximum(LEVELS * error, (LEVELS - 1) * error).mean(axis=0)
    return {
        "mae": float(np.abs(error[:, 1]).mean()),
        "rmse": float(np.sqrt(np.mean(error[:, 1] ** 2))),
        "pinball": float(pinball.mean()),
        "coverage_80": float(np.mean((actual >= quantiles[:, 0]) & (actual <= quantiles[:, 2]))),
        **{
            f"coverage_p{int(q * 100)}": float(np.mean(actual <= quantiles[:, i]))
            for i, q in enumerate(LEVELS)
        },
        **{f"pinball_p{int(q * 100)}": float(pinball[i]) for i, q in enumerate(LEVELS)},
    }
