"""Build country_lists/country_names_iso2.csv — the all-country reference for direct affiliation
country attribution.

Source: GeoNames country names carried by every location in the frozen global ROR dump
(data/external/ror/ror_data_v2_latest.json; local, no network), plus a short explicit list of
ISO 3166-1 entities absent from that dump. AU membership from country_lists/au54_countries.csv.
Deterministic: rows sorted by ISO2; the dump hash is checked against the frozen value.

Run from the repository root:  .venv\\Scripts\\python.exe code/utils/build_country_reference.py
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROR_DUMP = ROOT / "data/external/ror/ror_data_v2_latest.json"
ROR_DUMP_SHA = "8ae38a071b8b16349ea06b9f389c3b30917206838749a3ffaa9315a98a21abb3"
AU54 = ROOT / "country_lists/au54_countries.csv"
OUT = ROOT / "country_lists/country_names_iso2.csv"

ISO3_TO_ISO2_AU = {
    "DZA": "DZ", "AGO": "AO", "BEN": "BJ", "BWA": "BW", "BFA": "BF", "BDI": "BI", "CPV": "CV", "CMR": "CM",
    "CAF": "CF", "TCD": "TD", "COM": "KM", "COG": "CG", "CIV": "CI", "COD": "CD", "DJI": "DJ", "EGY": "EG",
    "GNQ": "GQ", "ERI": "ER", "SWZ": "SZ", "ETH": "ET", "GAB": "GA", "GMB": "GM", "GHA": "GH", "GIN": "GN",
    "GNB": "GW", "KEN": "KE", "LSO": "LS", "LBR": "LR", "LBY": "LY", "MDG": "MG", "MWI": "MW", "MLI": "ML",
    "MRT": "MR", "MUS": "MU", "MAR": "MA", "MOZ": "MZ", "NAM": "NA", "NER": "NE", "NGA": "NG", "RWA": "RW",
    "STP": "ST", "SEN": "SN", "SYC": "SC", "SLE": "SL", "SOM": "SO", "ZAF": "ZA", "SSD": "SS", "SDN": "SD",
    "TZA": "TZ", "TGO": "TG", "TUN": "TN", "UGA": "UG", "ZMB": "ZM", "ZWE": "ZW",
}
# ISO 3166-1 entities not present as ROR/GeoNames locations in the frozen dump
EXPLICIT = {"MH": "Marshall Islands", "NR": "Nauru", "SH": "Saint Helena", "AI": "Anguilla",
            "BL": "Saint Barthelemy", "MF": "Saint Martin", "IO": "British Indian Ocean Territory",
            "TK": "Tokelau", "WF": "Wallis and Futuna", "NF": "Norfolk Island", "PN": "Pitcairn"}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    if sha(ROR_DUMP) != ROR_DUMP_SHA:
        sys.exit(f"ROR dump hash differs from frozen {ROR_DUMP_SHA}")
    names: dict[str, set[str]] = {}
    for rec in json.load(open(ROR_DUMP, encoding="utf-8")):
        for loc in rec.get("locations", []):
            g = loc.get("geonames_details") or {}
            if g.get("country_code"):
                names.setdefault(g["country_code"], set()).add(g["country_name"])
    clash = {k: v for k, v in names.items() if len(v) != 1}
    if clash:
        sys.exit(f"ISO2 codes with several GeoNames names: {clash}")
    rows = {k: (next(iter(v)), "ror_geonames") for k, v in names.items()}
    for k, v in EXPLICIT.items():
        rows.setdefault(k, (v, "explicit_iso3166"))
    with open(AU54, encoding="utf-8") as f:
        au = {ISO3_TO_ISO2_AU[r["iso3"]] for r in csv.DictReader(f)}
    if not au <= set(rows) or len(au) != 54:
        sys.exit("AU-54 ISO2 codes missing from the reference")
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["iso2", "country_name", "source", "au_member"])
        for k in sorted(rows):
            w.writerow([k, rows[k][0], rows[k][1], k in au])
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} entities ({len(au)} AU)  sha256 {sha(OUT)}")


if __name__ == "__main__":
    main()
