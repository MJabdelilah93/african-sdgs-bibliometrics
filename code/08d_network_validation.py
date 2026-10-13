"""08d_network_validation.py — independent validation of the network/collaboration data (Stage 08).

Does NOT import code/08_network_collaboration.py, code/utils/collab_methods.py or
code/utils/country_normalisation.py. Country resolution for the deterministic sample uses an independent
text resolver (embedded below); all pair/metric/table checks are recomputed from enriched.csv with plain
csv/itertools.
Writes provenance/v2/network_independent_validation.json and logs/08d_network_validation.log.
"""
import csv
import html
import itertools
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
csv.field_size_limit(2**31 - 1)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LOG = open(ROOT / "provenance/v2/logs/08d_network_validation.log", "w", encoding="utf-8")
CHECKS = []


def say(m):
    print(m)
    LOG.write(m + "\n")


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "pass": bool(ok), "detail": str(detail)[:600]})
    say(f"[{'PASS' if ok else 'FAIL'}] {name} {str(detail)[:300]}")


def decode(t):
    prev = None
    while prev != t:
        prev, t = t, html.unescape(re.sub(r"&\s+amp;", "&", t))
    return t


# ── embedded verbatim from code/02d_stage2_validation.py ──
def fold(s):  # independent normaliser: apostrophes, accents, case, spaces
    s = str(s).replace("’", "'").replace("‘", "'")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split()).strip(" .;:")


def decode(t):
    prev = None
    while prev != t:
        prev, t = t, html.unescape(re.sub(r"&\s+amp;", "&", t))
    return t


# canonical names (GeoNames reference + AU-54) — independent of the Stage 02 variant list
canon = {}
for r in csv.DictReader(open(ROOT / "country_lists/country_names_iso2.csv", encoding="utf-8")):
    canon[fold(r["country_name"])] = r["iso2"]
I32 = dict(p.split(":") for p in ("DZA:DZ AGO:AO BEN:BJ BWA:BW BFA:BF BDI:BI CPV:CV CMR:CM CAF:CF TCD:TD COM:KM COG:CG "
           "CIV:CI COD:CD DJI:DJ EGY:EG GNQ:GQ ERI:ER SWZ:SZ ETH:ET GAB:GA GMB:GM GHA:GH GIN:GN GNB:GW KEN:KE LSO:LS "
           "LBR:LR LBY:LY MDG:MG MWI:MW MLI:ML MRT:MR MUS:MU MAR:MA MOZ:MZ NAM:NA NER:NE NGA:NG RWA:RW STP:ST SEN:SN "
           "SYC:SC SLE:SL SOM:SO ZAF:ZA SSD:SS SDN:SD TZA:TZ TGO:TG TUN:TN UGA:UG ZMB:ZM ZWE:ZW").split())
AU = set(I32.values())
for r in csv.DictReader(open(ROOT / "country_lists/au54_countries.csv", encoding="utf-8")):
    canon[fold(r["country_name_scopus"])] = I32[r["iso3"]]
    canon[fold(r["country_name_official"])] = I32[r["iso3"]]
# independent resolution of a segment's country (text only; same documented policy, re-implemented)
US_CODES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
               "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP".split())
US_NAMES = {"alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida",
            "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland",
            "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
            "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma",
            "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah",
            "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia"}
# documented Scopus variant table (policy DATA, copied as literals; matching logic here is independent)
EXTRA = {
    "bahamas": "BS",
    "brunei darussalam": "BN",
    "cape verde": "CV",
    "congo": "CG",
    "congo republic": "CG",
    "congo-brazzaville": "CG",
    "cote d'ivoire": "CI",
    "cote divoire": "CI",
    "czech republic": "CZ",
    "d.r. congo": "CD",
    "democratic republic congo": "CD",
    "democratic republic of congo": "CD",
    "democratic republic of the congo": "CD",
    "dr congo": "CD",
    "drc": "CD",
    "east timor": "TL",
    "england": "GB",
    "falkland islands (malvinas)": "FK",
    "federated states of micronesia": "FM",
    "gambia": "GM",
    "great britain": "GB",
    "guinea bissau": "GW",
    "holy see": "VA",
    "iran, islamic republic of": "IR",
    "islamic republic of iran": "IR",
    "ivory coast": "CI",
    "kingdom of eswatini": "SZ",
    "kingdom of saudi arabia": "SA",
    "korea": "KR",
    "ksa": "SA",
    "lao people's democratic republic": "LA",
    "libyan arab jamahiriya": "LY",
    "macau": "MO",
    "macedonia": "MK",
    "netherlands": "NL",
    "north korea": "KP",
    "northern ireland": "GB",
    "palestinian territories": "PS",
    "republic of congo": "CG",
    "republic of guinea": "GN",
    "republic of korea": "KR",
    "republic of the congo": "CG",
    "reunion": "RE",
    "russian federation": "RU",
    "saint kitts and nevis": "KN",
    "saint martin (french part)": "MF",
    "saint vincent and the grenadines": "VC",
    "sao tome": "ST",
    "sao tome and principe": "ST",
    "scotland": "GB",
    "sint maarten (dutch part)": "SX",
    "south korea": "KR",
    "state of palestine": "PS",
    "swaziland": "SZ",
    "syrian arab republic": "SY",
    "the bahamas": "BS",
    "the gambia": "GM",
    "the netherlands": "NL",
    "turkey": "TR",
    "turkiye": "TR",
    "u.k.": "GB",
    "u.s.a": "US",
    "u.s.a.": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "united republic of tanzania": "TZ",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "vatican city state": "VA",
    "viet nam": "VN",
    "virgin islands (british)": "VG",
    "virgin islands (u.s.)": "VI",
    "wales": "GB",
}
CONGO_FORMS = {"drc", "dr congo", "d.r. congo", "democratic republic congo", "democratic republic of congo",
               "democratic republic of the congo", "republic of the congo", "republic of congo", "congo republic",
               "congo-brazzaville"}


def cc_of(tok):
    return canon.get(tok) or EXTRA.get(tok)


def resolve(seg):
    """('one', c) | ('ambiguous', set) | ('none', None) | ('us_state', None)"""
    parts = [p.strip() for p in seg.split(",") if p.strip()]
    if not parts:
        return "none", None
    tail = [fold(p) for p in parts[-3:]]
    m = [(t, cc_of(t)) for t in tail if cc_of(t)]
    last = parts[-1].strip().strip(".")
    if cc_of(tail[-1]) is None and ((last.upper() in US_CODES and len(last) == 2) or tail[-1] in US_NAMES):
        return "us_state", None
    if any(t == "congo" for t, _ in m) and any(t in CONGO_FORMS for t, _ in m):
        m = [(t, c) for t, c in m if t != "congo"]
    if cc_of(tail[-1]) == "US" and any(t in US_NAMES or t == "georgia" or (p.strip().upper() in US_CODES and len(p.strip()) == 2)
                                        for t, p in zip(tail[:-1], parts[-3:][:-1])):
        m = [(t, c) for t, c in m if c == "US"]
    cs = {c for _, c in m}
    return ("one", next(iter(cs))) if len(cs) == 1 else ("ambiguous", cs) if cs else ("none", None)


# ── end embedded ──
S = lambda s: [x for x in s.split(";") if x]  # noqa: E731
R = ROOT / "results"


def rd(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))


geo_src = (ROOT / "code/05a_thematic_map_F6.R").read_text(encoding="utf-8")
GEO = {t.lower() for t in re.findall(r'"([^"]*)"', re.search(r"GEO_TERMS\s*<-\s*tolower\(c\((.*?)\)\)", geo_src, re.S).group(1))}
rc = {r["EID"]: r for r in rd(ROOT / "data/processed/network/record_countries.csv")}
ror_name = {}
for r in json.load(open(ROOT / "data/external/ror/ror_africa_v2.json", encoding="utf-8")):
    ror_name[r["id"]] = next((n["value"] for n in r.get("names", []) if "ror_display" in n.get("types", [])), r["id"])

pf, pfr = Counter(), defaultdict(float)
pubs, intl = Counter(), Counter()
paper = Counter()
kocc, kco = Counter(), Counter()
ipubs, ipair = Counter(), Counter()
f11c, f11k, f11j = Counter(), Counter(), Counter()
f11ck, f11kj = Counter(), Counter()
first_seen = {"c": {}, "k": {}, "j": {}}
GEO11 = {"africa", "south africa", "nigeria", "ethiopia", "kenya", "ghana", "uganda", "tanzania", "egypt", "morocco",
         "algeria", "tunisia", "sub-saharan africa", "developing countries", "developing country", "west africa",
         "east africa", "north africa", "southern africa"}
ISO2_NAME11 = {"DZ": "Algeria", "AO": "Angola", "BJ": "Benin", "BW": "Botswana", "BF": "Burkina Faso", "BI": "Burundi",
               "CV": "Cabo Verde", "CM": "Cameroon", "CF": "Cent. Afr. Rep.", "TD": "Chad", "KM": "Comoros", "CG": "Congo",
               "CD": "DR Congo", "CI": "Cote d'Ivoire", "DJ": "Djibouti", "EG": "Egypt", "GQ": "Eq. Guinea", "ER": "Eritrea",
               "SZ": "Eswatini", "ET": "Ethiopia", "GA": "Gabon", "GM": "Gambia", "GH": "Ghana", "GN": "Guinea",
               "GW": "Guinea-Bissau", "KE": "Kenya", "LS": "Lesotho", "LR": "Liberia", "LY": "Libya", "MG": "Madagascar",
               "MW": "Malawi", "ML": "Mali", "MR": "Mauritania", "MU": "Mauritius", "MA": "Morocco", "MZ": "Mozambique",
               "NA": "Namibia", "NE": "Niger", "NG": "Nigeria", "RW": "Rwanda", "ST": "Sao Tome & Pr.", "SN": "Senegal",
               "SC": "Seychelles", "SL": "Sierra Leone", "SO": "Somalia", "ZA": "South Africa", "SS": "South Sudan",
               "SD": "Sudan", "TZ": "Tanzania", "TG": "Togo", "TN": "Tunisia", "UG": "Uganda", "ZM": "Zambia", "ZW": "Zimbabwe"}
sample_bad, table_bad, sample_n, n = [], 0, 0, 0
with open(ROOT / "data/processed/enriched.csv", encoding="utf-8", newline="") as f:
    r = csv.reader(f)
    h = next(r)
    ie, ia, iac, iau, irr, ik, ij = (h.index(c) for c in ("EID", "Affiliations", "affiliation_countries", "au_countries",
                                                          "ror_ids", "keywords_harmonised", "Source title"))
    for row in r:
        n += 1
        e = row[ie]
        cs = sorted(set(S(row[iac])))
        au = set(S(row[iau]))
        if n % 100 == 1:                           # deterministic sample: every 100th record
            sample_n += 1
            own = set()
            for seg in decode(row[ia]).split(";"):
                if seg.strip():
                    k, c = resolve(seg)
                    if k == "one":
                        own.add(c)
            if own != set(S(rc[e]["countries"])) and len(sample_bad) < 20:
                sample_bad.append((e, sorted(own), rc[e]["countries"]))
        if cs != S(rc[e]["countries"]) or sorted(au) != S(rc[e]["au_countries"]):
            table_bad += 1
        prs = list(itertools.combinations(cs, 2))
        for a, b in prs:
            pf[(a, b)] += 1
            pfr[(a, b)] += 1 / len(prs)
        for c in cs:
            pubs[c] += 1
            intl[c] += len(cs) >= 2
        if au:
            non = len(cs) - len(au)
            paper["africa_involved_records"] += 1
            paper["single_country"] += len(cs) == 1
            paper["international"] += len(cs) >= 2
            paper["multi_au"] += len(au) >= 2
            paper["au_and_non_au"] += non >= 1
            paper["multi_au_and_non_au"] += len(au) >= 2 and non >= 1
            paper["intra_african_only"] += len(au) >= 2 and non == 0
            paper["africa_non_africa_only"] += len(au) == 1 and non >= 1
        kws = []
        for t in row[ik].split(";"):
            t = t.strip()
            if t and t.lower() not in GEO and t not in kws:
                kws.append(t)
        kocc.update(kws)
        for a, b in itertools.combinations(sorted(kws), 2):
            kco[(a, b)] += 1
        rr = sorted(set(S(row[irr])))
        ipubs.update(rr)
        for a, b in itertools.combinations(rr, 2):
            ipair[(a, b)] += 1
        # Figure 11 (independent): first AU country in segment order
        fc = None
        for seg in decode(row[ia]).split(";"):
            if seg.strip():
                k, c = resolve(seg)
                if k == "one" and c in AU:
                    fc = ISO2_NAME11[c]
                    break
        kl = [t.strip() for t in row[ik].split(";") if t.strip() and t.strip().lower() not in GEO11]
        jn = row[ij].strip().rstrip(".,;").title() if row[ij].strip() else None
        for d, key in (("c", fc), ("j", jn)):
            if key and key not in first_seen[d]:
                first_seen[d][key] = n
        for t in kl:
            if t not in first_seen["k"]:
                first_seen["k"][t] = n
        if fc:
            f11c[fc] += 1
        f11k.update(kl)
        if jn:
            f11j[jn] += 1
        if fc and kl and jn:
            for t in kl:
                f11ck[(fc, t)] += 1
                f11kj[(t, jn)] += 1

check("N01 country sets: independent resolver on every 100th record = Stage 08 sets; full table = Stage 02 fields",
      not sample_bad and table_bad == 0, f"sample {sample_n}; mismatches {sample_bad[:5]}; table mismatches {table_bad}")
typ = lambda a, b: {2: "AA", 1: "AN", 0: "NN"}[(a in AU) + (b in AU)]  # noqa: E731
T, TR = Counter(), defaultdict(float)
for k, v in pf.items():
    T[typ(*k)] += v
    TR[typ(*k)] += pfr[k]
summ = {r["metric"]: r for r in rd(R / "collaboration_summary.csv")}
check("N02 pair generation: unordered distinct pairs, total", sum(pf.values()) == sum(int(float(summ[f"pair_weight_full_{t}"]["value"])) for t in ("AA", "AN", "NN")), sum(pf.values()))
check("N03 full-pair weights by type", all(T[t] == int(float(summ[f"pair_weight_full_{t}"]["value"])) for t in ("AA", "AN", "NN")), dict(T))
recs_pairs = sum(1 for v in rc.values() if int(v["n_countries"]) >= 2)
check("N04 fractional-pair conservation", abs(sum(pfr.values()) - recs_pairs) < 1e-6, f"{sum(pfr.values()):.4f} vs {recs_pairs}")
check("N05/N06 AA, AN, NN fractional totals", all(abs(TR[t] - float(summ[f"pair_weight_fractional_{t}"]["value"])) < 1e-4 for t in ("AA", "AN", "NN")),
      {k: round(v, 3) for k, v in TR.items()})
fs, frs = T["AA"] / (T["AA"] + T["AN"]), TR["AA"] / (TR["AA"] + TR["AN"])
check("N07 intra-African link shares", abs(fs - float(summ["intra_african_link_share_full"]["value"])) < 1e-6 and
      abs(frs - float(summ["intra_african_link_share_fractional"]["value"])) < 1e-6, f"full {fs:.6f} fractional {frs:.6f}")
check("N08 paper-level counts", all(paper[k] == int(float(summ[k]["value"])) for k in paper) and
      paper["multi_au_and_non_au"] == int(float(summ["mixed_intra_and_external"]["value"])), dict(paper))
edges = {(r["iso2_a"], r["iso2_b"]): r for r in rd(R / "country_collaboration_edges.csv")}
nodes = {r["iso2"]: r for r in rd(R / "country_collaboration_nodes.csv")}
tls = Counter()
for (a, b), v in pf.items():
    tls[a] += v
    tls[b] += v
check("N09 Figure 9 edge/node tables", set(edges) == set(pf) and all(int(float(edges[k]["weight_full"])) == v for k, v in pf.items())
      and all(int(nodes[c]["publications"]) == pubs[c] and int(nodes[c]["international_publications"]) == intl[c]
              and int(float(nodes[c]["total_link_strength"])) == tls[c] for c in pubs), f"{len(pf)} edges, {len(pubs)} nodes")
mp = {l.split("\t")[0]: l.split("\t")[1] for l in open(R / "vosviewer/F9_country_africa_involved_full_map.txt", encoding="utf-8").read().splitlines()[1:]}
lab2iso = {v["country"]: k for k, v in nodes.items()}
nw = [l.split("\t") for l in open(R / "vosviewer/F9_country_africa_involved_full_network.txt", encoding="utf-8").read().splitlines()]
ok9 = all(pf.get(tuple(sorted((lab2iso[mp[a]], lab2iso[mp[b]])))) == int(float(w)) for a, b, w in nw)
check("N09b VOSviewer F9 network file = Africa-involved edges", ok9 and len(nw) == sum(1 for k in pf if typ(*k) != "NN"), len(nw))
kn = {r["keyword"]: r for r in rd(R / "keyword_network_nodes.csv")}
kmin = min(int(v["occurrences"]) for v in kn.values())
check("N10 keyword occurrence counts", all(int(kn[k]["occurrences"]) == kocc[k] for k in kn) and
      sum(1 for v in kocc.values() if v >= kmin) == len(kn), f"{len(kn)} nodes (>= {kmin})")
ke = rd(R / "keyword_network_edges.csv")
exp_ke = {k: v for k, v in kco.items() if k[0] in kn and k[1] in kn}
check("N11 keyword co-occurrence edges", len(ke) == len(exp_ke) and all(exp_ke.get((r["keyword_a"], r["keyword_b"])) == int(r["cooccurrences"]) for r in ke), len(ke))
inn = {r["ror_id"]: r for r in rd(R / "institution_network_nodes.csv")}
ine = {(r["ror_id_a"], r["ror_id_b"]): int(float(r["weight_full"])) for r in rd(R / "institution_network_edges.csv")}
check("N12 institution nodes/edges", ine == dict(ipair) and all(int(inn[k]["publications"]) == v for k, v in ipubs.items())
      and all(inn[k]["name"] == ror_name.get(k, "") for k in inn), f"{len(inn)} nodes, {len(ine)} edges")


def top(cnt, d):
    return [k for k, _ in sorted(cnt.items(), key=lambda x: (-x[1], first_seen[d][x[0]]))[:15]]


tc, tk, tj = top(f11c, "c"), top(f11k, "k"), top(f11j, "j")
fl = rd(R / "F11_three_field_flow_data.csv")
prov = json.load(open(ROOT / "provenance/v2/F11_three_field_provenance.json", encoding="utf-8"))
ck_total = sum(f11ck[(c, k)] for c in tc for k in tk)
kj_total = sum(f11kj[(k, j)] for k in tk for j in tj)
check("N13 Figure 11 top-15 sets and flow totals",
      [c for c, _ in prov["top_countries"]] == tc and [k for k, _ in prov["top_keywords"]] == tk and
      [v for _, v in prov["top_countries"]] == [f11c[c] for c in tc] and
      sum(int(r["value"]) for r in fl if r["flow"] == "country_to_keyword") == ck_total and
      sum(int(r["value"]) for r in fl if r["flow"] == "keyword_to_journal") == kj_total,
      f"countries {tc}; flows {ck_total}+{kj_total}")
npass = sum(c["pass"] for c in CHECKS)
say(f"SUMMARY: {npass}/{len(CHECKS)} PASS")
json.dump({"validator": "code/08d_network_validation.py", "checks": CHECKS, "n_pass": npass, "n_checks": len(CHECKS),
           "intra_african_link_share": {"full": fs, "fractional": frs}, "paper_level": dict(paper)},
          open(ROOT / "provenance/v2/network_independent_validation.json", "w", encoding="utf-8"), indent=1)
LOG.close()
sys.exit(0 if npass == len(CHECKS) else 1)
