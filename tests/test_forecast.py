import numpy as np
import pandas as pd
import pytest

from ice_network.demand import generate
from ice_network.forecast import Forecaster, future_frame, reconstruct, scores
from ice_network.simulator import history
from ice_network.world import Config


def test_reconstruction_is_past_only_and_respects_sales() -> None:
    c = Config(days=60)
    observed, _ = history(c, generate(c))
    early = observed[observed.day < 30]
    a, b = reconstruct(early), reconstruct(observed)
    pd.testing.assert_series_equal(a.reconstructed, b[b.day < 30].reconstructed)
    assert (b.reconstructed >= b.sales).all()
    with pytest.raises(ValueError, match="evaluator-only"):
        reconstruct(observed.assign(latent_demand=999))


@pytest.mark.parametrize("name", ["seasonal", "hurdle"])
def test_forecasts_are_ordered_and_do_not_see_future(name: str) -> None:
    c = Config(days=60)
    observed, _ = history(c, generate(c))
    model = Forecaster(name).fit(observed[observed.day < 49])
    result = model.predict(future_frame(49, 28, c))
    assert result.values.shape == (48, 4)
    assert (np.diff(result.values, axis=1) >= 0).all()
    assert (result.values >= 0).all()
    assert result.at(0.95).shape == (4, 12)
    with pytest.raises(ValueError, match="strictly earlier"):
        model.predict(future_frame(48, 28, c))


def test_pinball_and_interval_coverage() -> None:
    result = scores(np.array([10.0, 20.0]), np.array([[0, 10, 15, 18], [15, 20, 25, 30]]))
    assert result["mae"] == 0
    assert result["coverage_80"] == 1
    assert result["pinball_p50"] == 0
