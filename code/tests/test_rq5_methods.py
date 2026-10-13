"""Synthetic tests for code/utils/rq5_methods.py (no real data).

Run from the repository root:  .venv\\Scripts\\python.exe code/tests/test_rq5_methods.py
Plain asserts (pytest is not part of the pinned environment).
"""
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import rq5_methods as M  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def multi_sdg_weighting():
    assert M.parse_sdgs("3, 7,3,18,x, 17") == [3, 7, 17]
    c = list(M.record_contributions([1, 2, 3], ["KE"], "fractional"))
    assert len(c) == 3 and all(abs(w - 1 / 3) < 1e-15 for _, _, w in c)


@test
def multi_country_weighting_and_conservation():
    au = {"KE", "NG", "ZA"}
    cc = M.parse_countries("NG;KE;NG; ZA;US", au)          # repeated NG, non-AU US
    assert cc == ["KE", "NG", "ZA"]
    frac = list(M.record_contributions([4, 9], cc, "fractional"))
    assert len(frac) == 6 and all(abs(w - 1 / 6) < 1e-15 for *_, w in frac)
    assert abs(sum(w for *_, w in frac) - 1.0) < 1e-12          # record total = 1
    full = list(M.record_contributions([4, 9], cc, "full"))
    assert all(abs(w - 0.5) < 1e-15 for *_, w in full)
    assert abs(sum(w for *_, w in full) - 3.0) < 1e-12          # record total = m
    assert list(M.record_contributions([4], [], "fractional")) == []
    # random records: conservation of the fractional scheme
    rng = np.random.default_rng(0)
    tot = 0.0
    for _ in range(500):
        k = rng.integers(1, 6); m = rng.integers(1, 4)
        s = list(rng.choice(np.arange(1, 18), k, replace=False))
        c = list(rng.choice(["A", "B", "C", "D"], m, replace=False))
        tot += sum(w for *_, w in M.record_contributions(s, c, "fractional"))
    assert abs(tot - 500) < 1e-9


@test
def zero_retention_and_shares():
    w = np.zeros((2, 17)); w[0, :5] = [1, 2, 3, 4, 0]; w[0, 5] = 10
    sh = M.shares_from_weights(w)
    assert abs(np.nansum(sh[0]) - 1) < 1e-12
    assert sh[0, 4] == 0 and sh[0, 16] == 0                     # true zeros stay 0
    assert np.isnan(sh[1]).all()                                # no output -> no portfolio
    assert M.research_coverage(w)[0] == 5
    d = np.full(17, 50.0); d[13] = np.nan
    s, x, y = M.country_pairs(sh[0], d, "retain")
    assert len(s) == 16 and 14 not in s and (x == 0).sum() == 11
    s2, x2, _ = M.country_pairs(sh[0], d, "positive_only")
    assert len(s2) == 5 and (x2 > 0).all()


@test
def iso3_crosswalk_uniqueness_logic():
    # the crosswalk join must be by ISO3, independent of names
    sdr = {"COD": "Congo, Dem. Rep.", "COG": "Congo, Rep."}
    au = {"COD": "Democratic Republic Congo", "COG": "Congo"}
    joined = {k: sdr.get(k) for k in au}
    assert joined["COD"] == "Congo, Dem. Rep." and len(set(joined.values())) == 2


@test
def eligibility_rule():
    r = np.array([17, 10, 9, 17]); i = np.array([16, 14, 17, 13])
    assert M.eligibility(r, i, 10, 14).tolist() == [True, True, False, False]
    assert M.exclusion_reason(9, 13, 10, 14) == "research coverage 9 < 10; implementation coverage 13 < 14"
    assert M.implementation_coverage(np.array([[1, np.nan, 3.0]]))[0] == 2


@test
def spearman_matches_scipy_and_rowwise():
    rng = np.random.default_rng(1)
    for _ in range(200):
        n = rng.integers(5, 18)
        x = rng.integers(0, 4, n).astype(float)               # many ties
        y = rng.normal(size=n).round(1)
        r_ref = spearmanr(x, y).statistic
        r_row = M.rowwise_spearman(x[None, :], y[None, :])[0]
        if np.isnan(r_ref):
            assert np.isnan(r_row)
        else:
            assert abs(r_ref - r_row) < 1e-12
    assert np.isnan(M.rowwise_spearman(np.ones((1, 5)), np.arange(5.0)[None, :])[0])


@test
def bootstrap_pair_resampling():
    x = np.array([0.0, 0.1, 0.2, 0.3, 0.05, 0.4, 0.0, 0.15])
    y = np.array([10.0, 20, 30, 40, 50, 60, 70, 80])
    b1 = M.pair_bootstrap(x, y, 500, 42, "KEN")
    b2 = M.pair_bootstrap(x, y, 500, 42, "KEN")
    assert b1 == b2                                               # reproducible
    assert b1 != M.pair_bootstrap(x, y, 500, 42, "NGA")           # per-country stream
    assert b1["valid"] + b1["invalid"] == 500
    # pairs preserved: resampled (x, y) pairs only ever come from original pairs
    rng = np.random.default_rng(M.country_seed_sequence(42, "KEN"))
    idx = rng.integers(0, len(x), size=(500, len(x)))
    orig = set(zip(x, y))
    assert all((a, b) in orig for a, b in zip(x[idx].ravel(), y[idx].ravel()))
    # first 1000 rows of a 10k draw equal the 1k draw (stream extension)
    r1 = np.random.default_rng(M.country_seed_sequence(42, "KEN")).integers(0, 8, size=(1000, 8))
    r10 = np.random.default_rng(M.country_seed_sequence(42, "KEN")).integers(0, 8, size=(10000, 8))
    assert (r1 == r10[:1000]).all()
    # all-constant research -> every replicate invalid, nothing replaced
    bc = M.pair_bootstrap(np.zeros(6), np.arange(6.0), 100, 42, "KEN")
    assert bc["valid"] == 0 and bc["invalid"] == 100 and np.isnan(bc["ci_low"])


@test
def median_quadrant_ties():
    assert M.classify_quadrant(0.5, 50, 0.5, 50) == "HH"          # ties at threshold -> high
    assert M.classify_quadrant(0.49, 50, 0.5, 50) == "LH"
    assert M.classify_quadrant(0.5, 49.9, 0.5, 50) == "HL"
    assert M.classify_quadrant(0.0, 10, 0.1, 50) == "LL"
    vals = np.array([0.0, 0.0, 0.1, 0.2])                         # even n: median = 0.05
    med = np.median(vals)
    assert [M.classify_quadrant(v, 0, med, 0)[0] for v in vals] == ["L", "L", "H", "H"]


@test
def summaries_and_ties():
    assert M.n_tied(np.array([0, 0, 1, 2, 2, 2])) == 5
    s = M.summarise_rhos(np.array([-0.5, 0.0, 0.3, np.nan]), np.array([-0.9, -0.4, 0.1, np.nan]),
                         np.array([-0.1, 0.4, 0.6, np.nan]))
    assert s["n"] == 3 and s["n_negative"] == 1 and s["n_zero"] == 1 and s["n_positive"] == 1
    assert s["n_ci_below_zero"] == 1 and s["n_ci_above_zero"] == 1
    assert M.ci_position(-0.3, -0.01) == "entirely_below_zero" and M.ci_position(-0.1, 0.2) == "includes_zero"


if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {t.__name__}: {e!r}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} tests passed")
    sys.exit(1 if failed else 0)
