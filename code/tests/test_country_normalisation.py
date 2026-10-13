"""Unit tests for code/utils/country_normalisation.py (uses the committed reference CSVs only).

Run from the repository root:  .venv\\Scripts\\python.exe code/tests/test_country_normalisation.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
from utils.country_normalisation import (CountryNormaliser, decode_affiliations, split_segments,  # noqa: E402
                                         norm_token)

N = CountryNormaliser(ROOT / "country_lists/country_names_iso2.csv", ROOT / "country_lists/au54_countries.csv")
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def seg(s):
    return N.segment(s).primary


@test
def congo_variants():
    assert seg("Univ, Kinshasa, Democratic Republic Congo") == "CD"
    assert seg("Univ, Kinshasa, Democratic Republic of the Congo") == "CD"
    assert seg("Univ, Kinshasa, DR Congo") == "CD"
    assert seg("Univ, Kinshasa, DRC") == "CD"
    assert seg("Inst, Brazzaville, Congo") == "CG"
    assert seg("Inst, Brazzaville, Republic of Congo") == "CG"
    assert seg("Inst, Brazzaville, Republic of the Congo") == "CG"


@test
def cote_divoire_and_tanzania():
    assert seg("Univ, Abidjan, Côte d’Ivoire") == "CI"
    assert seg("Univ, Abidjan, Cote d'Ivoire") == "CI"
    assert seg("Univ, Abidjan, Ivory Coast") == "CI"
    assert seg("Univ, Dar es Salaam, Tanzania") == "TZ"
    assert seg("Univ, Dar es Salaam, United Republic of Tanzania") == "TZ"
    assert seg("Univ, Dodoma, Tanzania, United Republic of") == "TZ"


@test
def guinea_family_strict_boundaries():
    assert seg("Univ, Conakry, Guinea") == "GN"
    assert seg("Univ, Bissau, Guinea-Bissau") == "GW"
    assert seg("Univ, Bissau, Guinea Bissau") == "GW"
    assert seg("Univ, Malabo, Equatorial Guinea") == "GQ"
    assert seg("Univ, Lae, Papua New Guinea") == "PG"
    assert seg("Univ, Niamey, Niger") == "NE" and seg("Univ, Lagos, Nigeria") == "NG"
    assert seg("Univ, Juba, South Sudan") == "SS" and seg("Univ, Khartoum, Sudan") == "SD"


@test
def usa_uk_variants():
    for c in ("United States", "USA", "U.S.A.", "United States of America"):
        assert seg(f"Dept, Boston, MA, {c}") == "US", c
    for c in ("United Kingdom", "UK", "England", "Scotland", "Wales", "Northern Ireland"):
        assert seg(f"Dept, City, {c}") == "GB", c


@test
def us_state_codes_never_countries():
    assert seg("Dept, Boston, MA") is None                  # MA is not Morocco
    assert N.segment("Dept, Boston, MA").status == "us_state_terminated"
    assert seg("Dartmouth, Lebanon, NH") is None            # not Lebanon
    assert seg("Dept, Atlanta, GA") is None                 # not Gabon
    assert seg("Dept, Baltimore, Maryland") is None
    assert seg("Dept, Bloomington, IN") is None             # not India


@test
def trailing_non_country_parts():
    assert seg("Univ, Lagos, Nigeria, 100001") == "NG"
    assert seg("Univ, Lagos, Nigeria, PMB 12, 100001") == "NG"
    sb = N.segment("Dept, Univ of Benin, Benin, 300238, Nigeria")       # two countries named -> ambiguous
    assert sb.primary is None and sb.status == "country_ambiguous" and sb.explicit == {"NG", "BJ"}
    assert seg("Department of Medicine") is None


@test
def other_variants():
    pairs = {"Russian Federation": "RU", "Viet Nam": "VN", "South Korea": "KR", "Korea": "KR",
             "Syrian Arab Republic": "SY", "Libyan Arab Jamahiriya": "LY", "Türkiye": "TR", "Turkey": "TR",
             "Swaziland": "SZ", "Eswatini": "SZ", "Cape Verde": "CV", "Cabo Verde": "CV", "Brunei Darussalam": "BN",
             "Macao": "MO", "Palestine": "PS", "Czech Republic": "CZ", "Netherlands": "NL", "Guyana": "GY",
             "KSA": "SA", "Sao Tome and Principe": "ST", "São Tomé and Príncipe": "ST",
             "Gambia": "GM", "The Gambia": "GM", "Hong Kong": "HK", "Taiwan": "TW", "Reunion": "RE",
             "Réunion": "RE", "Bosnia and Herzegovina": "BA", "North Macedonia": "MK"}
    for name, code in pairs.items():
        assert seg(f"X, Y, {name}") == code, name


@test
def entities_decoded_before_split():
    s = "London School of Hygiene &amp; Tropical Medicine, London, United Kingdom; X, Lima, Peru"
    assert split_segments(s) == ["London School of Hygiene & Tropical Medicine, London, United Kingdom", "X, Lima, Peru"]
    assert split_segments("A & amp; B, City, Kenya") == ["A & B, City, Kenya"]
    assert split_segments("A &amp; amp; B, City, Kenya") == ["A & B, City, Kenya"]
    assert decode_affiliations("Ecole Nationale Sup&#x00E9;rieure, Dakar, Senegal").endswith("Senegal")


@test
def record_level_dedup_and_au():
    r = N.record("A, Nairobi, Kenya; B, Mombasa, Kenya; C, Boston, MA, United States; D, Boston, MA; E, Kampala, Uganda")
    assert r.countries == {"KE", "US", "UG"} and r.au == {"KE", "UG"}
    assert r.n_segments == 5 and r.n_unresolved == 1 and r.n_us_state_terminated == 1
    assert N.record("").countries == set()


@test
def reference_integrity():
    assert len(N.au) == 54
    assert all(c in N.name for c in N.alias.values())
    assert norm_token("  CÔTE D’IVOIRE. ") == "cote d'ivoire"


@test
def multi_country_collapse_and_ambiguity():
    # deterministic Congo collapse (text only)
    assert seg("Univ of Kinshasa, Kinshasa, Democratic Republic of the Congo, Congo") == "CD"
    assert seg("Dept, School of Public Health, University of Kinshasa, Democratic Republic of the Congo, Kinshasa, Congo") == "CD"
    assert seg("Univ, Bukavu, Democratic Republic of Congo, Congo") == "CD"
    assert seg("Kinshasa School of Public Health, DRC, Kinshasa, Congo") == "CD"
    assert seg("Univ, Kinshasa, DR Congo, Congo") == "CD"
    assert seg("Inst, Brazzaville, Republic of the Congo, Congo") == "CG"
    # US state structure
    assert seg("Dartmouth-Hitchcock Medical Center, Lebanon, NH, United States") == "US"
    assert seg("Georgia Southern University, Statesboro, Georgia, United States") == "US"
    assert seg("University of South Carolina, Colombia, SC, United States") == "US"
    # genuinely multi-country -> ambiguous, no country
    for s_ in ("University of Zambia School of Natural Sciences, Lusaka, Zambia, Sudan",
               "Department of Economics, University of Namibia, Windhoek, Namibia, South Africa",
               "Hong Kong Polytechnic University, Hong Kong, China",
               "Centre de Recherche en Sante de Nouna, Burkina Faso, London, United Kingdom"):
        sc = N.segment(s_)
        assert sc.primary is None and sc.status == "country_ambiguous" and len(sc.explicit) == 2, s_
    r = N.record("University of Zambia, Lusaka, Zambia, Sudan; X, Nairobi, Kenya")
    assert r.au == {"KE"} and r.n_country_ambiguous == 1                  # ambiguous segment contributes nothing
    assert N.record("University of Namibia, Windhoek, Namibia, South Africa").au == set()


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
