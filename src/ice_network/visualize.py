"""Export an offline, read-only 2D/3D replay of a completed backtest."""

import json
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

import pandas as pd

from ice_network.world import BARS, DEPOTS

FIELDS = [
    "day",
    "bar",
    "sales",
    "latent_demand",
    "closing",
    "melt",
    "receipts",
    "stockout",
    "p10",
    "p50",
    "p90",
    "p95",
    "temperature",
    "event",
]


def replay_data(out: Path) -> dict:
    required = [
        "config.json",
        "policy_daily.csv",
        "policy_forecasts.csv",
        "orders.csv",
        "policies.csv",
        "truth.csv",
    ]
    missing = [name for name in required if not (out / name).is_file()]
    if missing:
        raise ValueError(f"Run the backtest first; missing: {', '.join(missing)}")
    config = json.loads((out / "config.json").read_text())
    daily = pd.read_csv(out / "policy_daily.csv")
    forecasts = pd.read_csv(out / "policy_forecasts.csv")
    truth = pd.read_csv(out / "truth.csv")
    summaries = pd.read_csv(out / "policies.csv")
    orders = pd.read_csv(out / "orders.csv")
    keys = ["run", "day", "bar"]
    daily = daily.merge(
        forecasts[keys + ["p10", "p50", "p90", "p95"]], on=keys, how="left", validate="one_to_one"
    )
    daily = daily.merge(
        truth[["day", "bar", "event"]], on=["day", "bar"], how="left", validate="many_to_one"
    )
    days = sorted(daily.day.unique().tolist())
    if daily.event.isna().any() or len(days) != config["days"] - config["warmup"]:
        raise ValueError("Incomplete replay; finish the backtest before exporting")
    runs = {}
    for name, frame in daily.groupby("run", sort=True):
        frame = frame.sort_values(["day", "bar"])
        expected = pd.MultiIndex.from_product([days, range(len(BARS))], names=["day", "bar"])
        if not frame.set_index(["day", "bar"]).index.equals(expected):
            raise ValueError(f"Incomplete bar/day grid for {name}")
        if not name.startswith("naive/") and frame.p50.isna().any():
            raise ValueError(f"Missing forecasts for {name}")
        if ((frame.sales + frame.lost) != frame.latent_demand).any():
            raise ValueError(f"Demand ledger does not balance for {name}")
        # to_json converts missing naive forecasts to JSON null, never a fictitious zero.
        rows = json.loads(frame[FIELDS].to_json(orient="values", double_precision=5))
        routes = orders[orders.run == name].drop(columns="run")
        arrivals = routes.groupby(["arrival", "bar"]).bags.sum()
        missing_receipts = sum(
            max(0, r.receipts - arrivals.get((r.day, r.bar), 0)) for r in frame.itertuples()
        )
        summary = summaries[summaries.run == name]
        if len(summary) != 1:
            raise ValueError(f"Missing or duplicate summary for {name}")
        runs[name] = {
            "rows": rows,
            "orders": json.loads(routes.to_json(orient="records")),
            "summary": json.loads(summary.to_json(orient="records"))[0],
            "unlogged_receipts": float(missing_receipts),
        }
    if set(runs) != set(summaries.run):
        raise ValueError("Run summaries do not match the daily ledger")
    return {
        "config": config,
        "fields": FIELDS,
        "days": days,
        "runs": runs,
        "bars": [
            {"id": i, "name": b.name, "lat": b.lat, "lon": b.lon, "capacity": b.capacity}
            for i, b in enumerate(BARS)
        ],
        "depots": [asdict(d) for d in DEPOTS],
    }


def export_replay(out: Path) -> Path:
    data = replay_data(out)
    web = files("ice_network").joinpath("web")
    # Escape '<' so embedded data cannot terminate the script element.
    payload = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    document = web.joinpath("replay.html").read_text()
    for marker, content in {
        "/* REPLAY_CSS */": web.joinpath("replay.css").read_text(),
        "/* REPLAY_DATA */": payload,
        "/* THREE_BUNDLE */": web.joinpath("three.min.js").read_text(),
        "/* THREE_LICENSE */": web.joinpath("THREE-LICENSE.txt").read_text(),
        "/* REPLAY_JS */": web.joinpath("replay.js").read_text(),
        "/* SCENE_JS */": web.joinpath("scene.js").read_text(),
    }.items():
        document = document.replace(marker, content)
    destination = out / "replay.html"
    destination.write_text(document)
    return destination
