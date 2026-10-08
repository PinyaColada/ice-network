"""Paired-world rolling-origin replay with policy-specific censored histories."""

import copy
import json
import platform
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from ice_network.forecast import LEVELS, Forecaster, future_frame, reconstruct, scores
from ice_network.policies import order
from ice_network.simulator import Simulator, historical_orders
from ice_network.world import BARS, Config


def forecast_metrics(rows: pd.DataFrame, group: list[str]) -> pd.DataFrame:
    metrics = []
    for key, sample in rows.groupby(group, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        metrics.append(
            {
                **dict(zip(group, key, strict=True)),
                "n": len(sample),
                **scores(
                    sample.actual.to_numpy(),
                    sample[[f"p{int(q * 100)}" for q in LEVELS]].to_numpy(),
                ),
            }
        )
    return pd.DataFrame(metrics)


def common_forecasts(c: Config, truth: pd.DataFrame, observed: pd.DataFrame) -> pd.DataFrame:
    """Evaluate candidates on identical incumbent observations, separately from policy replay."""
    rows = []
    for name in ("seasonal", "hurdle"):
        model = Forecaster(name, c.seed)
        for day in range(c.warmup, c.days):
            if (day - c.warmup) % c.retrain_every == 0:
                model.fit(observed[observed.day < day])
            temperature = float(observed.loc[observed.day == day, "temperature"].iloc[0])
            pred = model.predict(future_frame(day, temperature, c, horizon=3))
            for i, r in enumerate(pred.frame.itertuples()):
                if r.day >= c.days:
                    continue
                actual = int(
                    truth.loc[(truth.day == r.day) & (truth.bar == r.bar), "latent_demand"].iloc[0]
                )
                rows.append(
                    {
                        "model": name,
                        "origin": day,
                        "day": r.day,
                        "bar": r.bar,
                        "horizon": r.day - day,
                        "actual": actual,
                        **dict(
                            zip([f"p{int(q * 100)}" for q in LEVELS], pred.values[i], strict=True)
                        ),
                    }
                )
    return pd.DataFrame(rows)


def replay(c: Config, truth: pd.DataFrame, out: Path) -> pd.DataFrame:
    initial = Simulator(c)
    for day in range(c.warmup):
        today = truth[truth.day == day]
        initial.start_day(day, float(today.temperature.iloc[0]))
        initial.place(historical_orders(initial, day))
        initial.close_day(today)
    experiments = [("naive", "none")] + [
        (policy, model)
        for model in ("seasonal", "hurdle")
        for policy in ("median", "quantile", "optimizer")
    ]
    summaries, ledgers, solver_logs, orders, predictions = [], [], [], [], []
    for policy, name in experiments:
        print(f"Replaying {policy}/{name} ...", flush=True)
        sim = copy.deepcopy(initial)
        model = Forecaster(name, c.seed) if name != "none" else None
        opening = sim.inventory.sum() + sum(s.bags for s in sim.pipeline)
        run = f"{policy}/{name}"
        for day in range(c.warmup, c.days):
            today = truth[truth.day == day]
            temperature = float(today.temperature.iloc[0])
            sim.start_day(day, temperature)
            observed = pd.DataFrame(sim.records)
            forecast = None
            if model is not None:
                if (day - c.warmup) % c.retrain_every == 0:
                    model.fit(observed)
                forecast = model.predict(future_frame(day, temperature, c))
                for b in range(len(BARS)):
                    predictions.append(
                        {
                            "run": run,
                            "day": day,
                            "bar": b,
                            "actual": int(today.iloc[b].latent_demand),
                            **dict(
                                zip(
                                    [f"p{int(q * 100)}" for q in LEVELS],
                                    forecast.values[b],
                                    strict=True,
                                )
                            ),
                        }
                    )
                # The closing date is known. Do not optimize for imaginary October customers.
                forecast.values[forecast.frame.day.to_numpy() >= c.days] = 0
            plan = order(policy, sim, observed, forecast)
            sim.place(plan.quantities)
            sim.close_day(today)
            solver_logs.append(
                {
                    "run": run,
                    "day": day,
                    "status": plan.status,
                    "gap": plan.gap,
                    "service_slack": plan.service_slack,
                    "planning_objective": plan.objective,
                }
            )
        ledger = pd.DataFrame(sim.records)
        ledger = ledger[ledger.day >= c.warmup].copy()
        ledger["run"] = run
        actual = truth[truth.day >= c.warmup].latent_demand.to_numpy()
        ledger["latent_demand"] = actual  # Evaluation-only ledger, never passed to fit().
        ledger["lost"] = actual - ledger.sales.to_numpy()
        shipments = [s for s in sim.shipments if s.departure >= c.warmup]
        transport = sim.transport_cost(since=c.warmup)
        holding = c.holding_cost * ledger.closing.sum()
        melting = c.bag_cost * ledger["melt"].sum()
        overflow = c.bag_cost * ledger.overflow.sum()
        lost_cost = c.stockout_cost * ledger.lost.sum()
        final = sim.inventory.sum() + sum(s.bags for s in sim.pipeline)
        balance = (
            opening
            + sum(s.bags for s in shipments)
            - (ledger.sales.sum() + ledger["melt"].sum() + ledger.overflow.sum() + final)
        )
        if abs(balance) > 1e-6:
            raise AssertionError(f"ice ledger does not balance: {run}: {balance}")
        summaries.append(
            {
                "run": run,
                "policy": policy,
                "model": name,
                "total_cost": transport + holding + melting + overflow + lost_cost,
                "transport_cost": transport,
                "holding_cost": holding,
                "melting_cost": melting,
                "overflow_cost": overflow,
                "stockout_cost": lost_cost,
                "service": ledger.sales.sum() / actual.sum(),
                "lost_sales": ledger.lost.sum(),
                "melted_bags": ledger["melt"].sum(),
                "overflow_bags": ledger.overflow.sum(),
                "truck_trips": sum(s.trips for s in shipments),
                "ending_stock": sim.inventory.sum(),
                "ending_pipeline": sum(s.bags for s in sim.pipeline),
                "conservation_error": balance,
            }
        )
        # Include opening-pipeline routes for the replay, but exclude their costs above.
        orders.extend({"run": run, **asdict(s)} for s in sim.shipments if s.arrival >= c.warmup)
        ledgers.append(ledger)
        print(
            f"  cost €{summaries[-1]['total_cost']:,.0f}; fill rate {summaries[-1]['service']:.1%}",
            flush=True,
        )
    pd.concat(ledgers, ignore_index=True).to_csv(out / "policy_daily.csv", index=False)
    pd.DataFrame(orders).to_csv(out / "orders.csv", index=False)
    pd.DataFrame(solver_logs).to_csv(out / "solver.csv", index=False)
    prediction_rows = pd.DataFrame(predictions)
    prediction_rows.to_csv(out / "policy_forecasts.csv", index=False)
    forecast_metrics(prediction_rows, ["run"]).to_csv(
        out / "policy_forecast_metrics.csv", index=False
    )
    result = pd.DataFrame(summaries)
    result["meets_target"] = result.service >= c.service
    result.to_csv(out / "policies.csv", index=False)
    return result


def verdict(metrics: pd.DataFrame, policies: pd.DataFrame, service: float) -> dict:
    accuracy = metrics[metrics.horizon == 1].sort_values("mae")
    best_accuracy = accuracy.iloc[0].model
    candidates = policies[policies.policy == "optimizer"]
    eligible = candidates[candidates.service >= service].sort_values("total_cost")
    best_decision = None if eligible.empty else eligible.iloc[0].model
    reversal = best_decision is not None and best_decision != best_accuracy
    message = (
        "No optimizer candidate meets the service target."
        if best_decision is None
        else "Lower forecast MAE does not select the cheapest qualifying optimizer."
        if reversal
        else "The lowest-MAE forecaster also selects the cheapest qualifying optimizer."
    )
    return {
        "accuracy_metric": "MAE, one-day horizon, common incumbent history",
        "best_accuracy": best_accuracy,
        "best_qualifying_decision": best_decision,
        "target": service,
        "reversal_observed": reversal,
        "message": message,
    }


def investigate(c: Config, truth: pd.DataFrame, observed: pd.DataFrame, out: Path) -> None:
    """Post-hoc audit only: none of these evaluator-side statistics feed decisions."""
    reconstructed = reconstruct(observed)
    daily = pd.read_csv(out / "policy_daily.csv").merge(
        truth[["day", "bar", "event"]], on=["day", "bar"], validate="many_to_one"
    )
    by_event = daily.groupby(["run", "event"])[["latent_demand", "lost"]].sum().reset_index()
    by_event.to_csv(out / "loss_by_event.csv", index=False)
    solver = pd.read_csv(out / "solver.csv")
    solver = solver[solver.run.str.startswith("optimizer")]
    audit = {
        "seed": c.seed,
        "observed_bags": int(observed.sales.sum()),
        "reconstructed_bags": float(reconstructed.reconstructed.sum()),
        "true_bags_evaluator_only": int(truth.latent_demand.sum()),
        "solver_max_gap": float(solver.gap.max()),
        "solver_status_counts": solver.status.value_counts().to_dict(),
        "positive_slack_days": solver.groupby("run")
        .service_slack.apply(lambda x: int((x > 1e-6).sum()))
        .to_dict(),
    }
    (out / "investigation.json").write_text(json.dumps(audit, indent=2) + "\n")


def run(c: Config, truth: pd.DataFrame, observed: pd.DataFrame, out: Path) -> None:
    predictions = common_forecasts(c, truth, observed)
    predictions.to_csv(out / "common_forecasts.csv", index=False)
    metrics = forecast_metrics(predictions, ["model", "horizon"])
    metrics.to_csv(out / "forecast_metrics.csv", index=False)
    policies = replay(c, truth, out)
    investigate(c, truth, observed, out)
    result = verdict(metrics, policies, c.service)
    result["versions"] = {p: version(p) for p in ["numpy", "pandas", "scikit-learn", "pyscipopt"]}
    result["python"] = platform.python_version()
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["message"], flush=True)
    from ice_network.plots import backtest_plots

    backtest_plots(metrics, policies, result, out)
