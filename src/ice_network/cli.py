"""Reproducible entry points; run from any working directory."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ice_network.demand import generate
from ice_network.plots import simulator_plot
from ice_network.simulator import history
from ice_network.world import Config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["simulate", "run", "visualize"])
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--days", type=int, default=153)
    parser.add_argument("--service", type=float, default=0.95)
    args = parser.parse_args()
    if args.command == "visualize":
        from ice_network.visualize import export_replay

        try:
            destination = export_replay(args.output)
        except ValueError as error:
            parser.error(str(error))
        print(f"Open {destination.resolve()} in your browser (works offline).", flush=True)
        return
    c = Config(seed=args.seed, days=args.days, service=args.service)
    args.output.mkdir(parents=True, exist_ok=True)
    truth = generate(c)
    observed, _ = history(c, truth)
    truth.to_csv(args.output / "truth.csv", index=False)
    observed.to_csv(args.output / "observed.csv", index=False)
    (args.output / "config.json").write_text(json.dumps(asdict(c), indent=2) + "\n")
    simulator_plot(truth, observed, args.output)
    print(
        f"Saved {len(truth):,} bar-days to {args.output}; "
        f"sell-out rate: {observed.stockout.mean():.1%}",
        flush=True,
    )
    if args.command == "run":
        from ice_network.backtest import run

        run(c, truth, observed, args.output)
        from ice_network.visualize import export_replay

        print(f"Visual replay: {export_replay(args.output).resolve()}", flush=True)


if __name__ == "__main__":
    main()
