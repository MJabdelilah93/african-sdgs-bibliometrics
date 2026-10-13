"""Pure methods for the RQ5 research-implementation alignment analysis.

No I/O. Used by code/06_alignment_analysis.py and the synthetic tests in
code/tests/test_rq5_methods.py. The independent validator
(code/06b_alignment_validation.py) deliberately does NOT import this module.

Conventions
-----------
* Countries are rows, SDG1..SDG17 are columns (index 0..16) of float arrays.
* Implementation scores/deficits use NaN for "not available"; research
  weights/shares never use NaN for a country with output (true zeros stay 0).
"""
from __future__ import annotations

import numpy as np
from scipy.stats import rankdata, spearmanr

N_SDG = 17


# ── record parsing ─────────────────────────────────────────────────────────
def parse_sdgs(sdg_tags: str) -> list[int]:
    """Unique valid SDG numbers (1..17) from a comma-separated tag string, sorted."""
    out = set()
    for t in str(sdg_tags).split(","):
        t = t.strip()
        if t.isdigit() and 1 <= int(t) <= N_SDG:
            out.add(int(t))
    return sorted(out)


def parse_countries(match_countries: str, valid_iso2: set[str]) -> list[str]:
    """Unique AU ISO2 codes from a semicolon-separated string (repeats removed), sorted."""
    return sorted({c.strip() for c in str(match_countries).split(";") if c.strip() in valid_iso2})


def record_contributions(sdgs: list[int], countries: list[str], scheme: str):
    """Yield (iso2, sdg, weight) contributions of one record.

    scheme = "fractional": 1 / (k * m) per country-SDG cell (record total = 1)
    scheme = "full"      : 1 / k        per country-SDG cell (record total = m)
    """
    k, m = len(sdgs), len(countries)
    if k == 0 or m == 0:
        return
    if scheme == "fractional":
        w = 1.0 / (k * m)
    elif scheme == "full":
        w = 1.0 / k
    else:
        raise ValueError(scheme)
    for c in countries:
        for s in sdgs:
            yield c, s, w


# ── research shares / coverage ─────────────────────────────────────────────
def shares_from_weights(weights: np.ndarray) -> np.ndarray:
    """Row-normalise country x SDG weights over all 17 SDGs; zeros retained.

    Countries without any output get a row of NaN (no research portfolio)."""
    weights = np.asarray(weights, dtype=float)
    tot = weights.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        sh = np.where(tot > 0, weights / np.where(tot > 0, tot, 1.0), np.nan)
    return sh


def research_coverage(weights: np.ndarray) -> np.ndarray:
    """Number of SDGs with positive research contribution (before zero filling)."""
    return (np.asarray(weights) > 0).sum(axis=1)


def implementation_coverage(deficits: np.ndarray) -> np.ndarray:
    return (~np.isnan(np.asarray(deficits, dtype=float))).sum(axis=1)


def eligibility(research_cov: np.ndarray, impl_cov: np.ndarray, r_min: int, i_min: int) -> np.ndarray:
    return (np.asarray(research_cov) >= r_min) & (np.asarray(impl_cov) >= i_min)


def exclusion_reason(r_cov: int, i_cov: int, r_min: int, i_min: int) -> str:
    reasons = []
    if r_cov < r_min:
        reasons.append(f"research coverage {r_cov} < {r_min}")
    if i_cov < i_min:
        reasons.append(f"implementation coverage {i_cov} < {i_min}")
    return "; ".join(reasons)


# ── pairs / Spearman ───────────────────────────────────────────────────────
def country_pairs(share_row: np.ndarray, deficit_row: np.ndarray, zero_policy: str = "retain"):
    """Return (sdg_numbers, research, deficit) for one country.

    zero_policy "retain"       : every SDG with a non-missing implementation deficit
    zero_policy "positive_only": additionally drop SDGs with research share == 0
    """
    share_row = np.asarray(share_row, dtype=float)
    deficit_row = np.asarray(deficit_row, dtype=float)
    keep = ~np.isnan(deficit_row) & ~np.isnan(share_row)
    if zero_policy == "positive_only":
        keep &= share_row > 0
    elif zero_policy != "retain":
        raise ValueError(zero_policy)
    idx = np.flatnonzero(keep)
    return idx + 1, share_row[idx], deficit_row[idx]


def n_tied(values: np.ndarray) -> int:
    """Number of observations that share their value with at least one other observation."""
    _, counts = np.unique(np.asarray(values), return_counts=True)
    return int(counts[counts > 1].sum())


def spearman(x, y) -> tuple[float, float]:
    res = spearmanr(x, y)
    return float(res.statistic), float(res.pvalue)


# ── bootstrap ──────────────────────────────────────────────────────────────
def country_seed_sequence(seed: int, iso3: str) -> np.random.SeedSequence:
    """Order-independent per-country stream: SeedSequence([seed, int(ISO3 bytes)])."""
    return np.random.SeedSequence([int(seed), int.from_bytes(iso3.encode("ascii"), "big")])


def rowwise_spearman(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Spearman rho per row (average ranks for ties); NaN where a row is constant."""
    rx = rankdata(X, axis=1, method="average")
    ry = rankdata(Y, axis=1, method="average")
    rx -= rx.mean(axis=1, keepdims=True)
    ry -= ry.mean(axis=1, keepdims=True)
    num = (rx * ry).sum(axis=1)
    den = np.sqrt((rx * rx).sum(axis=1) * (ry * ry).sum(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        rho = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
    return np.clip(rho, -1.0, 1.0)


def pair_bootstrap(x, y, reps: int, seed: int, iso3: str) -> dict:
    """Resample n (research, deficit) PAIRS with replacement `reps` times.

    Nothing is skipped or replaced: replicates whose resampled research or deficit
    vector is constant have an undefined rho (NaN) and are counted as invalid.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    rng = np.random.default_rng(country_seed_sequence(seed, iso3))
    idx = rng.integers(0, n, size=(reps, n))
    X, Y = x[idx], y[idx]
    rho = rowwise_spearman(X, Y)
    const_x = np.ptp(X, axis=1) == 0
    const_y = np.ptp(Y, axis=1) == 0
    srt = np.sort(idx, axis=1)
    n_unique = 1 + (np.diff(srt, axis=1) != 0).sum(axis=1)
    valid = rho[~np.isnan(rho)]
    out = {
        "attempted": int(reps), "valid": int(valid.size), "invalid": int(np.isnan(rho).sum()),
        "invalid_constant_research_only": int((const_x & ~const_y).sum()),
        "invalid_constant_deficit_only": int((const_y & ~const_x).sum()),
        "invalid_constant_both": int((const_x & const_y).sum()),
        "resamples_lt3_unique_pairs": int((n_unique < 3).sum()),
        "unique_pairs_mean": float(n_unique.mean()), "unique_pairs_min": int(n_unique.min()),
        "unique_pairs_max": int(n_unique.max()),
        "boot_median": float(np.median(valid)) if valid.size else np.nan,
        "ci_low": float(np.percentile(valid, 2.5)) if valid.size else np.nan,
        "ci_high": float(np.percentile(valid, 97.5)) if valid.size else np.nan,
    }
    return out


def ci_position(lo: float, hi: float) -> str:
    if np.isnan(lo) or np.isnan(hi):
        return "undefined"
    if hi < 0:
        return "entirely_below_zero"
    if lo > 0:
        return "entirely_above_zero"
    return "includes_zero"


# ── quadrants ──────────────────────────────────────────────────────────────
QUADRANT_NAMES = {
    "HH": "high research / high deficit",
    "HL": "high research / low deficit",
    "LH": "low research / high deficit",
    "LL": "low research / low deficit",
}


def classify_quadrant(research: float, deficit: float, r_thr: float, d_thr: float) -> str:
    """'High' means value >= threshold (ties at the threshold are classified high)."""
    hr = research >= r_thr
    hd = deficit >= d_thr
    return ("H" if hr else "L") + ("H" if hd else "L")


def summarise_rhos(rho: np.ndarray, ci_lo: np.ndarray, ci_hi: np.ndarray) -> dict:
    rho = np.asarray(rho, dtype=float)
    ok = ~np.isnan(rho)
    r = rho[ok]
    if r.size == 0:
        return {"n": 0}
    return {
        "n": int(r.size), "median_rho": float(np.median(r)),
        "q1_rho": float(np.percentile(r, 25)), "q3_rho": float(np.percentile(r, 75)),
        "min_rho": float(r.min()), "max_rho": float(r.max()),
        "n_negative": int((r < 0).sum()), "n_zero": int((r == 0).sum()), "n_positive": int((r > 0).sum()),
        "n_ci_below_zero": int((np.asarray(ci_hi)[ok] < 0).sum()),
        "n_ci_above_zero": int((np.asarray(ci_lo)[ok] > 0).sum()),
    }
