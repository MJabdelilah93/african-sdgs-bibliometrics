"""Deterministic country attribution from Scopus affiliation text, independent of ROR.

Rules (documented in provenance/v2/stage2_affiliation_summary.json):
  * HTML entities are decoded BEFORE splitting segments on ';' ('&amp;' contains ';'; Scopus also
    emits a malformed '& amp;').
  * A segment's country is read from WHOLE comma-parts only (strict boundaries: 'Niger' never
    matches inside 'Nigeria', 'Guinea' never inside 'Papua New Guinea'). The last three
    comma-parts are scanned from the end; the first part equal to a country alias is the
    segment's PRIMARY country.
  * If the last comma-part is a US state/territory postal code or name (and not itself a country
    name), the segment is 'us_state_terminated' and gets NO country: state codes are never read as
    countries (e.g. 'MA' is not Morocco) and the scan does not continue to earlier parts
    (e.g. 'Lebanon, NH' is not Lebanon).
  * EXPLICIT countries = every country alias among the last three parts (used to restrict ROR
    candidates; a segment may name more than one).
  * Aliases: GeoNames names from country_lists/country_names_iso2.csv, AU-54 names from
    country_lists/au54_countries.csv, and the explicit Scopus variants below. An alias mapping to
    two different ISO2 codes raises an error.
"""
from __future__ import annotations

import csv
import html
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ISO3_TO_ISO2_AU = {
    "DZA": "DZ", "AGO": "AO", "BEN": "BJ", "BWA": "BW", "BFA": "BF", "BDI": "BI", "CPV": "CV", "CMR": "CM",
    "CAF": "CF", "TCD": "TD", "COM": "KM", "COG": "CG", "CIV": "CI", "COD": "CD", "DJI": "DJ", "EGY": "EG",
    "GNQ": "GQ", "ERI": "ER", "SWZ": "SZ", "ETH": "ET", "GAB": "GA", "GMB": "GM", "GHA": "GH", "GIN": "GN",
    "GNB": "GW", "KEN": "KE", "LSO": "LS", "LBR": "LR", "LBY": "LY", "MDG": "MG", "MWI": "MW", "MLI": "ML",
    "MRT": "MR", "MUS": "MU", "MAR": "MA", "MOZ": "MZ", "NAM": "NA", "NER": "NE", "NGA": "NG", "RWA": "RW",
    "STP": "ST", "SEN": "SN", "SYC": "SC", "SLE": "SL", "SOM": "SO", "ZAF": "ZA", "SSD": "SS", "SDN": "SD",
    "TZA": "TZ", "TGO": "TG", "TUN": "TN", "UGA": "UG", "ZMB": "ZM", "ZWE": "ZW",
}

# Scopus / common variants (each explicit and inspectable)
SCOPUS_VARIANTS = {
    "united states": "US", "usa": "US", "u.s.a": "US", "u.s.a.": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "great britain": "GB",
    "russian federation": "RU", "viet nam": "VN", "south korea": "KR", "republic of korea": "KR", "korea": "KR",
    "north korea": "KP", "syrian arab republic": "SY", "libyan arab jamahiriya": "LY", "turkey": "TR",
    "turkiye": "TR", "cote d'ivoire": "CI", "cote divoire": "CI", "ivory coast": "CI",
    "democratic republic congo": "CD", "democratic republic of the congo": "CD",
    "democratic republic of congo": "CD", "dr congo": "CD", "drc": "CD", "d.r. congo": "CD",
    "republic of the congo": "CG", "republic of congo": "CG", "congo": "CG", "congo republic": "CG",
    "congo-brazzaville": "CG", "swaziland": "SZ", "kingdom of eswatini": "SZ", "cape verde": "CV",
    "brunei darussalam": "BN", "macau": "MO", "lao people's democratic republic": "LA",
    "state of palestine": "PS", "palestinian territories": "PS", "macedonia": "MK", "czech republic": "CZ",
    "federated states of micronesia": "FM", "falkland islands (malvinas)": "FK",
    "virgin islands (british)": "VG", "virgin islands (u.s.)": "VI", "saint martin (french part)": "MF",
    "sint maarten (dutch part)": "SX", "east timor": "TL", "vatican city state": "VA", "holy see": "VA",
    "united republic of tanzania": "TZ", "gambia": "GM", "the gambia": "GM", "netherlands": "NL",
    "the netherlands": "NL", "saint kitts and nevis": "KN", "saint vincent and the grenadines": "VC",
    "bahamas": "BS", "the bahamas": "BS", "ksa": "SA", "kingdom of saudi arabia": "SA",
    "sao tome and principe": "ST", "sao tome": "ST", "guinea bissau": "GW", "republic of guinea": "GN",
    "iran, islamic republic of": "IR", "islamic republic of iran": "IR", "reunion": "RE",
}

# US state / territory postal codes and names: never countries; terminate the scan.
US_STATE_CODES = set(("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
                      "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP").split())
US_STATE_NAMES = {"alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
                  "florida", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
                  "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
                  "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
                  "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
                  "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
                  "washington", "west virginia", "wisconsin", "wyoming", "district of columbia"}

N_TRAILING_PARTS = 3
# explicit (non-bare) Congo state forms; a bare 'congo' next to one of these is redundant
CONGO_EXPLICIT_FORMS = {"democratic republic congo", "democratic republic of the congo", "democratic republic of congo",
                        "dr congo", "drc", "d.r. congo", "republic of the congo", "republic of congo", "congo republic",
                        "congo-brazzaville"}


def norm_token(s: str) -> str:
    """Unify apostrophes (before ASCII folding), strip accents, casefold, collapse spaces, trim punctuation."""
    s = str(s).replace("’", "'").replace("‘", "'").replace("`", "'")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = " ".join(s.casefold().split())
    return s.strip(" .;:")


def decode_affiliations(text: str) -> str:
    prev, s = None, str(text)
    while prev != s:
        prev, s = s, html.unescape(re.sub(r"&\s+amp;", "&", s))
    return s


def split_segments(text: str) -> list[str]:
    return [seg.strip() for seg in decode_affiliations(text).split(";") if seg.strip()]


@dataclass
class SegmentCountry:
    primary: str | None
    explicit: frozenset
    status: str          # 'country' | 'us_state_terminated' | 'none'


@dataclass
class RecordCountries:
    countries: set = field(default_factory=set)
    au: set = field(default_factory=set)
    n_segments: int = 0
    n_unresolved: int = 0
    n_us_state_terminated: int = 0
    n_country_ambiguous: int = 0
    unresolved_endings: list = field(default_factory=list)


class CountryNormaliser:
    def __init__(self, reference_csv: Path, au54_csv: Path):
        self.alias: dict[str, str] = {}
        self.name: dict[str, str] = {}
        self.sources: dict[str, str] = {}
        with open(reference_csv, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                self.name[r["iso2"]] = r["country_name"]
                self._add(r["country_name"], r["iso2"], "reference")
        with open(au54_csv, encoding="utf-8") as f:
            au_rows = list(csv.DictReader(f))
        self.au = {ISO3_TO_ISO2_AU[r["iso3"]] for r in au_rows}
        for r in au_rows:
            for n in (r["country_name_scopus"], r["country_name_official"]):
                self._add(n, ISO3_TO_ISO2_AU[r["iso3"]], "au54")
        for n, iso2 in SCOPUS_VARIANTS.items():
            self._add(n, iso2, "variant")
        unknown = {c for c in self.alias.values() if c not in self.name}
        if unknown:
            raise ValueError(f"aliases point to codes absent from the reference: {sorted(unknown)}")
        if len(self.au) != 54:
            raise ValueError("AU-54 list does not have 54 members")

    def _add(self, name: str, iso2: str, source: str) -> None:
        k = norm_token(name)
        if not k:
            return
        if k in self.alias and self.alias[k] != iso2:
            raise ValueError(f"alias conflict: '{k}' -> {self.alias[k]} ({self.sources[k]}) vs {iso2} ({source})")
        self.alias[k] = iso2
        self.sources.setdefault(k, source)

    def part_country(self, part: str) -> str | None:
        return self.alias.get(norm_token(part))

    @staticmethod
    def is_us_state(part: str) -> bool:
        p = part.strip().strip(".")
        return p.upper() in US_STATE_CODES and len(p) == 2 or norm_token(p) in US_STATE_NAMES

    def segment(self, seg: str) -> SegmentCountry:
        """Resolve the segment's country from the country mentions in its last three comma-parts.

        Text-only deterministic collapse rules (never consult ROR):
          * Congo: a bare 'Congo' part is redundant when an explicit Congo state is also named
            ('Democratic Republic of (the) Congo, Congo' / 'DR Congo, Congo' -> CD;
             'Republic of the Congo, Congo' -> CG).
          * US state structure: when the last part is the United States and another trailing part is
            a US state code/name, the segment is US ('Lebanon, NH, United States' is not Lebanon).
        One distinct country -> status 'country'; more than one -> 'country_ambiguous' (no country;
        callers must abstain); none -> 'none'; a bare US state as last part -> 'us_state_terminated'.
        """
        parts = [p for p in (x.strip() for x in seg.split(",")) if p]
        if not parts:
            return SegmentCountry(None, frozenset(), "none")
        tail = parts[-N_TRAILING_PARTS:]
        mentions = [(norm_token(p), self.part_country(p)) for p in tail]
        mentions = [(t, c) for t, c in mentions if c]
        if self.part_country(tail[-1]) is None and self.is_us_state(tail[-1]):
            return SegmentCountry(None, frozenset(c for _, c in mentions), "us_state_terminated")
        # Congo collapse: drop a bare 'congo' when an explicit Congo state form is present
        if any(t == "congo" for t, _ in mentions) and any(t in CONGO_EXPLICIT_FORMS for t, _ in mentions):
            mentions = [(t, c) for t, c in mentions if t != "congo"]
        # US state structure: '<state>, United States'
        if self.part_country(tail[-1]) == "US" and any(self.is_us_state(p) or norm_token(p) == "georgia"
                                                        for p in tail[:-1]):
            mentions = [(t, c) for t, c in mentions if c == "US"]
        countries = frozenset(c for _, c in mentions)
        if len(countries) == 1:
            return SegmentCountry(next(iter(countries)), countries, "country")
        if len(countries) > 1:
            return SegmentCountry(None, countries, "country_ambiguous")
        return SegmentCountry(None, countries, "none")

    def record(self, affiliations: str) -> RecordCountries:
        out = RecordCountries()
        for s in split_segments(affiliations):
            out.n_segments += 1
            sc = self.segment(s)
            if sc.primary:
                out.countries.add(sc.primary)
            else:
                out.n_unresolved += 1
                out.n_us_state_terminated += sc.status == "us_state_terminated"
                out.n_country_ambiguous += sc.status == "country_ambiguous"
                out.unresolved_endings.append(s.split(",")[-1].strip())
        out.au = out.countries & self.au
        return out
