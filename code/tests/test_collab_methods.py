"""Synthetic tests for code/utils/collab_methods.py (no real data).

Run from the repository root:  .venv\\Scripts\\python.exe code/tests/test_collab_methods.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import collab_methods as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
from utils.country_normalisation import CountryNormaliser  # noqa: E402
N = CountryNormaliser(ROOT / "country_lists/country_names_iso2.csv", ROOT / "country_lists/au54_countries.csv")
AU_SET = N.au
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def bibliometrix_substring_semantics():
    voc = ["SUDAN", "SOUTH SUDAN", "GUINEA", "PAPUA NEW GUINEA", "CONGO"]
    got = C.bibliometrix_au_co("UNIV, JUBA, SOUTH SUDAN; UNIV, PORT MORESBY, PAPUA NEW GUINEA", voc)
    assert {"SOUTH SUDAN", "SUDAN", "PAPUA NEW GUINEA", "GUINEA"} == got   # documented false positives
    assert C.bibliometrix_au_co("X, KINSHASA, DEMOCRATIC REPUBLIC CONGO", voc) == {"CONGO"}


@test
def pair_generation_and_counting():
    assert C.country_pairs(["KE", "US", "KE", "NG"]) == [("KE", "NG"), ("KE", "US"), ("NG", "US")]
    assert C.country_pairs(["KE"]) == [] and C.country_pairs([]) == []
    full = list(C.pair_weights(["KE", "US", "NG", "GB"], "full"))
    assert len(full) == 6 and all(w == 1.0 for *_, w in full)
    frac = list(C.pair_weights(["KE", "US", "NG", "GB"], "fractional"))
    assert abs(sum(w for *_, w in frac) - 1.0) < 1e-12              # record total = 1
    assert list(C.pair_weights(["KE"], "fractional")) == []


@test
def africa_classification_and_profiles():
    assert C.pair_type("KE", "NG", AU_SET) == "AA"
    assert C.pair_type("KE", "US", AU_SET) == "AN" and C.pair_type("US", "KE", AU_SET) == "AN"
    assert C.pair_type("US", "GB", AU_SET) == "NN"
    p = C.paper_profile(["KE", "NG", "US"], AU_SET)
    assert p["multi_au"] and p["au_and_non_au"] and p["multi_au_and_non_au"] and not p["intra_african_only"]
    assert C.paper_profile(["KE"], AU_SET)["domestic"] and not C.paper_profile(["KE"], AU_SET)["international"]
    assert C.paper_profile(["KE", "NG"], AU_SET)["intra_african_only"]
    assert C.paper_profile(["KE", "US", "GB"], AU_SET)["africa_non_africa_only"]
    assert not C.paper_profile(["US", "GB"], AU_SET)["africa_involved"]


@test
def keyword_cooccurrence():
    items = C.unique_items("hiv; malaria; hiv; africa;  ; tuberculosis", drop={"africa"})
    assert items == ["hiv", "malaria", "tuberculosis"]
    assert C.cooccurrence_pairs(items) == [("hiv", "malaria"), ("hiv", "tuberculosis"), ("malaria", "tuberculosis")]
    # association strength: symmetric, 2m c / (k_i k_j)
    assert abs(C.association_strength(2, 4, 5, 10) - 2.0) < 1e-12


@test
def institution_cooccurrence():
    ror = "https://ror.org/a;https://ror.org/b;https://ror.org/a"
    items = C.unique_items(ror)
    assert items == ["https://ror.org/a", "https://ror.org/b"]
    assert C.cooccurrence_pairs(items) == [("https://ror.org/a", "https://ror.org/b")]
    assert C.cooccurrence_pairs(["https://ror.org/a"]) == []


@test
def country_dedup_and_figure11_direct_country():
    rc = N.record("A, Nairobi, Kenya; B, Mombasa, Kenya; C, Boston, MA, United States; D, Lagos, Nigeria")
    assert rc.countries == {"KE", "US", "NG"} and rc.au == {"KE", "NG"}          # no duplicate country
    assert C.country_pairs(rc.countries) == [("KE", "NG"), ("KE", "US"), ("NG", "US")]
    # Figure 11 country = first AU country in affiliation order, from text only (never ROR)
    assert C.first_au_country(N, "X, London, United Kingdom; Y, Accra, Ghana; Z, Nairobi, Kenya") == "GH"
    assert C.first_au_country(N, "Univ of Zambia, Lusaka, Zambia, Sudan; Y, Accra, Ghana") == "GH"   # ambiguous skipped
    assert C.first_au_country(N, "X, Paris, France") is None
    # first AU country is always a member of the record's AU set
    aff = "Ministry of Health, Baghdad, Iraq; Hosp, Lilongwe, Malawi"
    assert C.first_au_country(N, aff) in N.record(aff).au


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
