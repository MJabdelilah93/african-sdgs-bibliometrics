"""Pure methods for the network / collaboration layer (Stage 08).

No I/O. Country attribution lives in utils/country_normalisation.py (shared with Stage 02);
this module keeps only network/collaboration functions. The independent validator does NOT
import this module.
"""
from __future__ import annotations

import itertools

from utils.country_normalisation import decode_affiliations, split_segments  # noqa: F401  (re-export)


def first_au_country(norm, affiliations: str) -> str | None:
    """First AU country in affiliation-segment order, via the Stage 02 normaliser `norm`
    (text only; ambiguous segments contribute nothing). Used for the Figure 11 country field."""
    for seg in split_segments(affiliations):
        c = norm.segment(seg).primary
        if c in norm.au:
            return c
    return None


def bibliometrix_au_co(c1_upper: str, vocab_names: list[str]) -> set[str]:
    """Emulation of bibliometrix 5.4.0 AU_CO for Scopus: names whose 'NAME;' occurs in C1 + ';'."""
    s = str(c1_upper) + ";"
    return {n for n in vocab_names if (n + ";") in s}


# ── collaboration pairs ────────────────────────────────────────────────────
def country_pairs(countries) -> list[tuple[str, str]]:
    """Each unordered pair of DISTINCT countries once (sorted)."""
    return list(itertools.combinations(sorted(set(countries)), 2))


def pair_weights(countries, scheme: str):
    """Yield (a, b, weight). full: 1 per pair; fractional: 1/p (record total = 1 when p > 0)."""
    pairs = country_pairs(countries)
    if not pairs:
        return
    w = 1.0 if scheme == "full" else 1.0 / len(pairs) if scheme == "fractional" else None
    if w is None:
        raise ValueError(scheme)
    for a, b in pairs:
        yield a, b, w


def pair_type(a: str, b: str, au: set[str]) -> str:
    return {2: "AA", 1: "AN", 0: "NN"}[(a in au) + (b in au)]


def paper_profile(countries, au: set[str]) -> dict:
    cs = set(countries)
    n_au = len(cs & au)
    n_non = len(cs - au)
    return {"n_countries": len(cs), "n_au": n_au, "n_non_au": n_non,
            "africa_involved": n_au >= 1, "international": len(cs) >= 2,
            "domestic": len(cs) == 1 and n_au == 1, "multi_au": n_au >= 2,
            "au_and_non_au": n_au >= 1 and n_non >= 1,
            "multi_au_and_non_au": n_au >= 2 and n_non >= 1,
            "intra_african_only": n_au >= 2 and n_non == 0,
            "africa_non_africa_only": n_au == 1 and n_non >= 1}


# ── keyword / institution co-occurrence ────────────────────────────────────
def unique_items(text: str, sep: str = ";", drop: set[str] | None = None) -> list[str]:
    items = []
    seen = set()
    for t in str(text).split(sep):
        t = t.strip()
        if not t or (drop and t.lower() in drop) or t in seen:
            continue
        seen.add(t)
        items.append(t)
    return items


def cooccurrence_pairs(items) -> list[tuple[str, str]]:
    return list(itertools.combinations(sorted(set(items)), 2))


def association_strength(c_ij: float, k_i: float, k_j: float, m: float) -> float:
    """VOSviewer association strength (Waltman, van Eck & Noyons 2010): a_ij = 2 m c_ij / (k_i k_j),
    k_i = total link weight of node i in the network, m = total link weight of the network."""
    return 2.0 * m * c_ij / (k_i * k_j)
