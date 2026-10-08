# Methodology and validation

[Back to the project](../README.md)

## The daily contract

1. Melt yesterday's closing stock: 2.5% plus 0.4 percentage points per degree above
   25°C, capped at 15%. Stock uses bag-equivalents; only whole bags can be sold.
   Fractional remnants stay in the ledger.
2. Receive shipments. Reserved storage includes **all** pipeline orders, so even
   zero future sales cannot cause overflow. This is deliberately conservative.
3. Order using morning temperature and past observations. Orders by 10:00 depart
   today; later orders depart tomorrow. Palma has a one-day fulfillment lead time;
   Alcudia has two. Production and fleet capacity are reserved on departure day.
4. Demand arrives; sales are `min(demand, floor(stock))`. A sell-out is observable;
   whether additional customers existed is hidden from forecasting code.

Demand includes weekday/holiday effects, a tourism peak, correlated weather, rain,
parties, cruises and three intermittent bars. Future events are hidden. Weather
forecasts decay the known morning anomaly toward climatology, never reading future
temperatures. June 24 and August 15 form a simplified synthetic holiday calendar.

Both models share the generator's smooth calendar/temperature normalization as a
prespecified structural assumption. This is a controlled demonstration, not evidence
of discovering seasonality from real data. Neither receives per-bar demand parameters,
future sales/events or latent demand.

Each trip serves one bar, costs €12 plus €0.32/km, and carries up to 360 bags. Orders
use 20-bag packs and a 40-bag MOQ per depot/bar delivery. Six trucks provide three
dispatch slots each per day; depot production is 2,100/1,500 bags per day. Route costs
use twice a 1.3× great-circle distance approximation. There is no multi-stop VRP,
driving-time schedule, overnight positioning or inter-depot repositioning cost.
Fulfillment lead time does not occupy a truck for multiple days. Refrigerated transit
has no shrinkage. The ledger checks, per bar:

```text
opening stock + opening pipeline + new orders
  = sales + melting + overflow waste + closing stock + closing pipeline
```

## Forecasts and decisions

**Reconstruction.** Match each sell-out to up to eight earlier uncensored days for
the same bar and weekday/weekend class in a 56-day window, ranked by temperature
distance. Normalize season/heat, take their mean, and lower-bound it by sales.
Without donors, retain the observed lower bound. Earlier reconstructions never use
later donors. Large demands remain underrepresented. An alternative is a censored
negative-binomial hurdle likelihood: use probability mass for uncensored observations
and survival probability above available stock for sell-outs. Stockout timestamps
would help; an entirely unobserved tail still requires assumptions.

**Seasonal baseline.** Group means plus empirical residual quantiles after calendar
normalization, preserving the mass at zero. **Boosted hurdle.** A gradient-boosted
occurrence classifier and eight positive-demand quantile regressors; transform the
conditional CDF through the hurdle probability. Sorting prevents quantile crossings.
Both publish P10/P50/P90/P95. MAE/RMSE use P50, a median rather than a mean; pinball
loss and coverage assess the distribution. Inclusive coverage at a discrete zero
atom can exceed its nominal quantile even for a calibrated distribution.

**Rules.** Naive uses the last seven days of censored sales. Median uses P50 (the
requested “forecast-mean” policy). Quantile uses the target quantile. All target a
lead-time-plus-one-day stock position, subtract pipeline stock, allow for melting,
round to packs and obey the same constraints. Greedy allocation prioritizes lowest
days of cover, then nearby depots. Summing daily quantiles is a stock-buffer heuristic,
not a quantile of total lead-time demand.

**MILP.** Integer case counts, delivery indicators and route trip counts are shared
across nine stratified scenarios over four days. Scenario balances apply melting
and timed receipts; binary complementarity forbids simultaneous closing stock and
lost demand. Production, fleet, MOQ and conservative storage constraints are hard.
The objective is transport + expected holding + melting + lost-sales cost. A soft
aggregate fill constraint on days reachable by new deliveries penalizes unmet service
by another €24/bag. Slack is reported, never presented as achieved service. The target
is not a per-bar or per-day guarantee.

Only today's dispatch is optimized; there are no future replenishment recourse
decisions in the four-day horizon. Draws ignore cross-bar/temporal dependence and use
a small, bounded tail approximation. The optimizer replans tomorrow. Single-thread
SCIP uses a deterministic 2,000-node budget and 1% gap tolerance; every day's status,
gap and slack are saved. No feasible incumbent is an error, not a silent fallback.

## Backtest and findings

The May–September 2025 world has 153 days: 49 shared warmup days and 104 evaluated
days. Each policy starts with identical stock/pipeline, replays the same demand and
weather, and retrains weekly on its own observations through yesterday. The known
closing date suppresses forecasts beyond the evaluation window. No new delivery
remains in transit at the end.

The headline's accuracy axis comes from a **separate common-history experiment** at
rolling horizons 0, 1 and 2. Policy forecasts also have their own metrics. Better
availability changes training data, so policy-specific errors cannot be interpreted
as a controlled forecaster ranking.

| Policy / forecaster | Total cost | Fill rate | Lost bags | Melted bags | Trips |
|---|---:|---:|---:|---:|---:|
| Naive | €642,706 | 56.7% | 51,163 | 627 | 762 |
| Median / seasonal | €288,232 | 82.3% | 20,941 | 1,181 | 956 |
| P95 / seasonal | €103,405 | 96.2% | 4,532 | 6,376 | 1,022 |
| Optimizer / seasonal | €105,271 | 96.1% | 4,646 | 7,131 | 1,025 |
| Median / hurdle | €336,082 | 78.9% | 24,923 | 1,026 | 968 |
| P95 / hurdle | €111,130 | 95.6% | 5,237 | 6,272 | 1,060 |
| Optimizer / hurdle | €105,553 | 96.1% | 4,660 | 7,301 | 1,034 |

Cost is **incremental replenishment cost**, not full business accounting: transport,
€0.015 per closing bag-day, €1.20 per melted/wasted bag, and €12 per lost sale.
Sold ice procurement/revenue are represented through the lost-contribution penalty,
not charged separately. Remaining ice is carried at book value and reported rather
than treated as a season-end loss. Planning slack penalties are excluded from realized
cost. Fill rate is total bags sold / total bags demanded.

The reproducible audit explains why the hoped-for reversal did not appear:

- The baseline has lower one-day MAE **and** mean pinball loss (13.77 versus 14.59).
  There is no clear tradeoff between a better center and a worse distribution here.
- Reconstruction raises historical sales from 75,282 to 113,704 estimated bags,
  but truth is 147,041. Common-history P95 coverage is only 67.6%/68.6%: similar
  uncensored days cannot recover all the missing tail.
- About 61% of the seasonal optimizer's lost bags occur on party/cruise days,
  which are unknown at ordering time. Better availability improves training data
  but cannot make surprise demand disappear.
- The P95 rule beats the MILP by €1,867: 114 fewer lost sales and about 755 fewer
  melted bags. A four-day model with only current orders can overstock; nine
  independent scenarios miss joint extremes. This is a plausible mechanism,
  not an ablation proving which approximation caused the gap.

`artifacts/` includes totals, both kinds of forecast scores, daily evaluator ledgers,
shipments, solver diagnostics, event losses, configuration, versions and three plots.
Compact results, figures and a published replay snapshot in `docs/index.html` are
committed. Generated ledgers and `artifacts/replay.html` are ignored and rebuilt by
the CLI; `make demo` refreshes the published snapshot from the current results.
Repeat runs in the pinned environment should match; bitwise agreement across CPU
architectures or different solver versions is not guaranteed.

Validation: sixteen Python tests and Ruff pass; the tests also pass in the Docker
build. The original season reproduced exactly across native and Docker runs. Adding
the visualization preserves policy totals, forecasts and daily ledgers exactly.
Browser checks cover data reconciliation, controls, playback, orbiting, mobile layout,
offline use and the WebGL fallback. To run the optional browser check:

```sh
npm install --prefix /tmp/ice-browser-qa playwright@1.55.1
/tmp/ice-browser-qa/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/ice-browser-qa/node_modules node tests/replay.browser.cjs
```

Node/Playwright are needed only for this browser test, not for generating or opening
the replay. `ICE_CHROMIUM_PATH` can point the test at an existing Chromium executable.

## What I would do next in production

Start with real sales, availability, stockout timestamps, weather forecasts as issued
and road travel times. Estimate reconstruction uncertainty. Model uncertain lead
times, shared heat/event shocks, multi-echelon depot stock and future replenishment
decisions. Add operator overrides, exception handling for broken freezers/late trucks,
and audit logs for every override. Test more seasons and cost/service sensitivities
before trusting small rankings; replace dispatch slots with actual vehicle shifts.

References: [PySCIPOpt installation](https://pyscipopt.readthedocs.io/en/latest/install.html)
and [quantile boosting](https://scikit-learn.org/1.5/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html).
