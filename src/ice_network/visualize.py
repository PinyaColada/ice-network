"""Export an offline, read-only 2D/3D replay of a completed backtest."""

import json
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

import pandas as pd

from ice_network.world import BARS, DEPOTS, distances

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


def operational_metrics(frame: pd.DataFrame, routes: pd.DataFrame, config: dict) -> dict:
    """Daily depot flows and weighted network ratios, derived without changing decisions.

    Depots have production limits, not modeled stock. Unused production is not ice.
    Opening-pipeline departures are excluded from evaluated transport cost, but their
    bags remain in transit until receipt. Undefined ratios are null, not zero.
    """
    km = distances()
    depot_rows, network_rows = [], []
    cumulative = {"sales": 0.0, "demand": 0.0, "waste": 0.0, "cost": 0.0}
    for day, rows in frame.groupby("day", sort=True):
        dispatched = routes[routes.departure == day]
        pipeline = routes[(routes.departure <= day) & (routes.arrival > day)]
        transport, kilometers = 0.0, 0.0
        for shipment in dispatched.itertuples():
            distance = float(2 * km[shipment.depot, shipment.bar] * shipment.trips)
            kilometers += distance
            transport += distance * config["km_cost"] + shipment.trips * config["fixed_trip_cost"]
        for d, depot in enumerate(DEPOTS):
            sent = dispatched[dispatched.depot == d]
            bags = int(sent.bags.sum())
            depot_rows.append(
                {
                    "day": int(day),
                    "depot": d,
                    "dispatched": bags,
                    "capacity": depot.production,
                    "unused_capacity": depot.production - bags,
                    "in_transit": int(pipeline[pipeline.depot == d].bags.sum()),
                    "trips": int(sent.trips.sum()),
                }
            )
        sold, demand = int(rows.sales.sum()), int(rows.latent_demand.sum())
        melted, overflow = float(rows["melt"].sum()), float(rows.overflow.sum())
        bags, trips = int(dispatched.bags.sum()), int(dispatched.trips.sum())
        holding = float(rows.closing.sum()) * config["holding_cost"]
        waste_cost = (melted + overflow) * config["bag_cost"]
        stockout = (demand - sold) * config["stockout_cost"]
        total = transport + holding + waste_cost + stockout
        cumulative["sales"] += sold
        cumulative["demand"] += demand
        cumulative["waste"] += melted + overflow
        cumulative["cost"] += total
        consumed = cumulative["sales"] + cumulative["waste"]
        network_rows.append(
            {
                "day": int(day),
                "sales": sold,
                "demand": demand,
                "lost": demand - sold,
                "closing": float(rows.closing.sum()),
                "in_transit": int(pipeline.bags.sum()),
                "melt": melted,
                "overflow": overflow,
                "dispatched": bags,
                "trips": trips,
                "round_trip_km": kilometers,
                "fill_rate": sold / demand if demand else None,
                "truck_load": bags / (trips * config["truck_capacity"]) if trips else None,
                "fleet_use": trips / (config["trucks"] * config["trips_per_truck"]),
                "production_use": bags / sum(d.production for d in DEPOTS),
                "transport_cost": transport,
                "holding_cost": holding,
                "waste_cost": waste_cost,
                "stockout_cost": stockout,
                "total_cost": total,
                "cumulative_cost": cumulative["cost"],
                "cost_per_sold_bag": cumulative["cost"] / cumulative["sales"]
                if cumulative["sales"]
                else None,
                "ice_yield": cumulative["sales"] / consumed if consumed else None,
                "cumulative_fill": cumulative["sales"] / cumulative["demand"]
                if cumulative["demand"]
                else None,
            }
        )
    return {"depots": depot_rows, "network": network_rows}


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
            "operations": operational_metrics(frame, routes, config),
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
