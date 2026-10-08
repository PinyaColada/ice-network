"""Small, static, exportable figures; all numbers come from saved experiment output."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from ice_network.world import BARS, DEPOTS, distances


def simulator_plot(truth: pd.DataFrame, observed: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout="constrained")
    ax = axes[0, 0]
    for i, b in enumerate(BARS):
        d = DEPOTS[distances()[:, i].argmin()]
        ax.plot([b.lon, d.lon], [b.lat, d.lat], color="#cccccc", lw=0.8)
        ax.scatter(b.lon, b.lat, s=b.capacity / 9, c="#157a86")
        ax.annotate(
            b.name.split(":")[0],
            (b.lon, b.lat),
            fontsize=8,
            xytext=(3, 4),
            textcoords="offset points",
        )
    for d in DEPOTS:
        ax.scatter(d.lon, d.lat, marker="s", s=95, color="#df7847")
        ax.annotate(
            f"{d.name} depot",
            (d.lon, d.lat),
            xytext=(4, -14),
            textcoords="offset points",
            fontsize=8,
        )
    ax.set(title="12 bars, 2 depots; marker size = storage", xlabel="Longitude", ylabel="Latitude")
    ax.set_aspect(1 / 0.77)
    daily = truth.groupby("date").latent_demand.sum()
    ax = axes[0, 1]
    ax.plot(daily.index, daily, label="Latent demand", color="#157a86")
    obs = observed.groupby("date").sales.sum()
    ax.plot(obs.index, obs, label="Observed sales", color="#df7847", alpha=0.85)
    ax.set(title="An empty freezer makes a misleading dataset", ylabel="Bags / day")
    ax.legend()
    ax = axes[1, 0]
    bar = 0
    t = truth[truth.bar == bar].iloc[:50]
    o = observed[observed.bar == bar].iloc[:50]
    ax.plot(t.date, t.latent_demand, label="Demand", color="#157a86")
    ax.step(o.date, o.sales, label="Sales", color="#df7847", where="mid")
    ax.plot(o.date, o.closing, label="Closing stock", color="#595959", alpha=0.7)
    ax.set(title=BARS[bar].name, ylabel="Bags")
    ax.legend(fontsize=8)
    ax = axes[1, 1]
    t = truth[truth.bar == 10].iloc[:50]
    ax.bar(t.date, t.latent_demand, color="#157a86")
    ax.set(title="Sant Elm: intermittent demand is not a small average", ylabel="Bags / day")
    for ax in (axes[0, 1], axes[1, 0], axes[1, 1]):
        ax.tick_params(axis="x", rotation=25)
    fig.suptitle("The chiringuito that occasionally runs out of ice", fontsize=17)
    fig.savefig(out / "simulator.png", dpi=150)
    plt.close(fig)


def backtest_plots(metrics: pd.DataFrame, policies: pd.DataFrame, result: dict, out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    accuracy = metrics[metrics.horizon == 1].set_index("model")
    for _, row in policies[policies.policy == "optimizer"].iterrows():
        color = "#157a86" if row.service >= result["target"] else "#df7847"
        axes[0].scatter(accuracy.loc[row.model, "mae"], row.total_cost / 1000, s=120, color=color)
        axes[0].annotate(
            f"{row.model}\nfill {row.service:.1%}",
            (accuracy.loc[row.model, "mae"], row.total_cost / 1000),
            xytext=(10, 6),
            textcoords="offset points",
            fontsize=10,
        )
    axes[0].margins(x=0.6, y=0.5)
    axes[0].set(
        xlabel="One-day forecast MAE on common history (bags)",
        ylabel="Optimizer realized cost (€ thousands)",
        title="Same optimizer, different forecaster",
    )
    ordered = policies.sort_values("total_cost")
    colors = ["#157a86" if ok else "#df7847" for ok in ordered.meets_target]
    axes[1].barh(ordered.run, ordered.total_cost / 1000, color=colors)
    for i, row in enumerate(ordered.itertuples()):
        axes[1].text(row.total_cost / 1000 + 0.5, i, f"{row.service:.1%}", va="center", fontsize=8)
    axes[1].set(
        xlabel="Total cost (€ thousands); labels = fill rate",
        title=f"Teal meets {result['target']:.0%} target; orange misses",
    )
    axes[1].set_xlim(0, ordered.total_cost.max() / 1000 * 1.20)
    axes[1].invert_yaxis()
    title = (
        "Better forecasts, worse ice decisions?"
        if result["reversal_observed"]
        else "The freezer has the final word"
    )
    fig.suptitle(title + "\n" + result["message"], fontsize=13)
    fig.savefig(out / "headline.png", dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for name, row in accuracy.iterrows():
        axes[0].plot(
            [0.1, 0.5, 0.9, 0.95],
            [row[f"coverage_p{q}"] for q in [10, 50, 90, 95]],
            "o-",
            label=name,
        )
    axes[0].plot([0, 1], [0, 1], "--", color="gray")
    axes[0].set(
        xlabel="Nominal quantile",
        ylabel="Observed P(demand ≤ forecast)",
        title="Common-history calibration, horizon 1",
    )
    axes[0].legend()
    axes[1].bar(accuracy.index, accuracy.pinball, color=["#157a86", "#df7847"])
    axes[1].set(ylabel="Mean pinball loss (bags)", title="P10 / P50 / P90 / P95")
    fig.savefig(out / "calibration.png", dpi=150)
    plt.close(fig)
