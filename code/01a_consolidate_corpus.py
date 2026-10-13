"""01a_consolidate_corpus.py
Stage 01a – consolidation of the deduplicated corpus.

Input is the Stage 01 output (code/01_deduplication.py), i.e. the deduplicated union of the 41 Scopus exports of
8 May 2026. This step produces the consolidated corpus that enters the eligibility screening (Stage 01b):

  1 SDG 2 assignment. SDG 2 membership is assigned exclusively from the SDG 2 exports of 7 October 2026, retrieved
    with the composed SDG 2 query (sdg_queries/composed/SDG02_full_{2015-2021,2022-2025}.txt; Aurora SDG Queries
    v5.0.3, AU-54 affiliation filter, articles and reviews) and the Scopus condition ORIG-LOAD-DATE BEF 20260509,
    which restricts retrieval to records loaded into Scopus before 9 May 2026. SDG 2 tags of the Stage 01 output are
    replaced by this assignment. Records of the SDG 2 exports are matched to the corpus by exact EID, by an EID merged
    in Stage 01 (provenance/stage3_dedup_log.csv, passes 2-3), by exact standardised DOI, and by fuzzy title for
    records without a DOI (token_set_ratio >= the configured threshold, same or adjacent year). Matched records keep
    the metadata of the 8 May 2026 export; unmatched SDG 2 records are added with their own metadata; duplicates among
    them follow the Stage 01 keeper rule. Records left without any SDG assignment are removed.
  2 Curated fuzzy-title decisions. Five Stage 01 fuzzy-title merge groups combine distinct publications (for example
    numbered report series or papers sharing a generic title). Their eight member publications are kept as separate
    records, each rebuilt from its own export rows with the Stage 01 keeper rule; the record that had absorbed them
    keeps the SDG tags of its own export rows. Seven republication or reprint groups remain merged under the counting
    rule. Three record pairs are kept separate when matching the SDG 2 exports (two different papers with similar
    titles; one DOI recorded for two different papers in Scopus).

Stage 01 rules are reused, not re-implemented: clean_title / merge_sdg_tags are compiled from code/01_deduplication.py
(definitions only, via ast) and its DOI / EID standardisation statements are executed from the same source; the title
threshold and year window come from config.yaml; eligibility() is imported from code/01b_scope_2015_2025.py to report
the number of eligible records.

Inputs (defaults are repository-relative):
  data/interim/deduplicated.csv                        Stage 01 output
  data/raw/                                            the 41 exports of 8 May 2026 (rows of the separated publications)
  data/raw/sdg2_2026-10-07/SDG02_AU54_2026-10-07_2015-2021.csv, ..._2022-2025.csv   SDG 2 exports of 7 October 2026
  provenance/stage3_dedup_log.csv, provenance/stage2_checksums.txt
Outputs:
  data/interim/consolidated.csv                        (written via .tmp; replaced only after every check passes)
  provenance/v2/stage1a_consolidation_summary.json

The input SHA-256 values below identify the exports used for the published analysis. Other exports can be processed
with --allow-other-inputs; the expected counts and digests then no longer apply.

Run from the repository root:
  python code/01a_consolidate_corpus.py
"""
import argparse
import ast
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.process import cdist as rf_cdist

HERE    = Path(__file__).resolve().parent
ARTICLE = HERE.parent
sys.path.insert(0, str(HERE))

from utils.checksums import sha256_file  # noqa: E402
from utils.config import cfg  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_VERSION  = "2.0.0"
STAGE01_SCRIPT  = HERE / "01_deduplication.py"
STAGE01B_SCRIPT = HERE / "01b_scope_2015_2025.py"
FILE_RE         = re.compile(r"^SDG(\d{2})_AU54_.*\.csv$")          # Stage 01 export-file pattern
SDG2_DIR        = ARTICLE / cfg["paths"]["raw_data"] / "sdg2_2026-10-07"
DEFAULTS = {
    "baseline":      ARTICLE / "data" / "interim" / "deduplicated.csv",
    "sdg2_part1":    SDG2_DIR / "SDG02_AU54_2026-10-07_2015-2021.csv",
    "sdg2_part2":    SDG2_DIR / "SDG02_AU54_2026-10-07_2022-2025.csv",
    "merge_log":     ARTICLE / "provenance" / "stage3_dedup_log.csv",
    "raw_dir":       ARTICLE / cfg["paths"]["raw_data"],
    "raw_checksums": ARTICLE / "provenance" / "stage2_checksums.txt",
    "output":        ARTICLE / "data" / "interim" / "consolidated.csv",
    "summary":       ARTICLE / "provenance" / "v2" / "stage1a_consolidation_summary.json",
}
# inputs of the published analysis (SHA-256 of the files as exported)
EXPECTED_INPUTS = {
    "baseline":   {"sha256": "c6977ca7e46a7862708dde54eca2024970d5bc2a0c25cb368717e957e8b0001b", "rows": 338_409},
    "sdg2_part1": {"sha256": "1550fcb2b034fddfd7ab580126b72999f31c66d02bdec1fdaf7d453ee34fd0dd", "rows": 12_556},
    "sdg2_part2": {"sha256": "b186717bc19611d159779907365f58d340bed84e45c151e4a31c059211a31152", "rows": 18_642},
}
SCOPUS_COLUMNS, RAW_FILES = 45, 41
# results of the published analysis (checked when the inputs above are used)
EXPECTED_RESULT = {
    "consolidated_rows": 345_069, "eligible_rows": 345_025, "removed": 2, "added": 6_654, "separated": 8,
    "sdg2_records": 31_190,
    "decision_digest": "ededc4a1f456d9ec2cd10c135c104673a8a1413051e3bcfd0641167a09ca9979",
    "output_digest": "f8b746b21af4252009df5a316abecadaefbdfaa9cb3c2c0a193351233b528c67",
}
# fuzzy-title merge groups of Stage 01 that combine distinct publications (record that absorbed them -> members)
SEPARATED_GROUPS = {
    "2-s2.0-85134875051": {"label": "India discrimination series (health care / age / weight)",
                           "members": ["2-s2.0-85134879943", "2-s2.0-85135285907"],
                           "reason": "distinct papers: perceived age and weight discrimination vs health-care discrimination "
                                     "(same authors and issue; different pages, samples and outcomes)"},
    "2-s2.0-85105709710": {"label": "Mexico older adults series (sleep / loneliness)",
                           "members": ["2-s2.0-85105710934"],
                           "reason": "distinct papers: loneliness vs short and long sleep (same authors and issue; "
                                     "different pages and outcomes); fuzzy-title similarity 95.197 (threshold 95)"},
    "2-s2.0-84925457520": {"label": "smoking cessation titles",
                           "members": ["2-s2.0-84929001183", "2-s2.0-84930606796", "2-s2.0-85016936355"],
                           "reason": "distinct papers by different authors in different journals; the two-word title "
                                     "'Smoking cessation' is a token subset of the other titles (token_set_ratio 100)"},
    "2-s2.0-105019185753": {"label": "foggara legal mechanisms",
                            "members": ["2-s2.0-105027907794"],
                            "reason": "published discussion of the article by a different author "
                                      "(issue 64 p563 vs issue 63 p285)"},
    "2-s2.0-85133710290": {"label": "African Elephant Specialist Group Chair reports",
                           "members": ["2-s2.0-85144649037"],
                           "reason": "distinct annual reports (Pachyderm vol 62, 2021 vs vol 63, 2022)"},
}
# records that absorbed separated publications and whose own export rows carry different SDG tags
EXPECTED_OWN_TAGS = {"2-s2.0-85134875051": "5", "2-s2.0-85133710290": "12,15"}
# resulting change in the number of records per SDG other than SDG 2 (consequence of the separation)
EXPECTED_NON_SDG2_DELTAS = {3: 3, 4: 1, 5: 2, 6: 1, 11: 1, 15: 1}
# republication / reprint groups kept as one record under the counting rule
RETAINED_GROUPS = {
    "2-s2.0-84939192713": {"label": "COPD update republications",
                           "absorbed": ["2-s2.0-84992690718", "2-s2.0-85016990925", "2-s2.0-85021275165"]},
    "2-s2.0-85014019079": {"label": "sewage-sludge copper republication", "absorbed": ["2-s2.0-85017373586"]},
    "2-s2.0-85016959205": {"label": "annual ADHD updates (2016 / 2017)", "absorbed": ["2-s2.0-85028629348"]},
    "2-s2.0-85017119723": {"label": "Lagos town-planning republication", "absorbed": ["2-s2.0-85036580195"]},
    "2-s2.0-85062634584": {"label": "World Kidney Day editorial reprints", "absorbed": ["2-s2.0-85066280336"]},
    "2-s2.0-85074444212": {"label": "tourism-perception publications", "absorbed": ["2-s2.0-85078234810"]},
    "2-s2.0-85081535905": {"label": "Côte d'Ivoire menstruation-study republication", "absorbed": ["2-s2.0-85089382487"]},
}
# pairs kept separate when matching the SDG 2 exports (SDG 2 export EID, corpus EID)
NONMERGE_PAIRS = [
    {"sdg2_eid": "2-s2.0-85105685135", "corpus_eid": "2-s2.0-85105709710", "expected_match": "fuzzy_title",
     "reason": "different papers (depression vs sleep among older adults in Mexico); token_set_ratio false positive"},
    {"sdg2_eid": "2-s2.0-85086332233", "corpus_eid": "2-s2.0-85086330842", "expected_match": "doi",
     "reason": "one DOI recorded in Scopus for two different papers (food-commodity futures prices vs moringa)"},
    {"sdg2_eid": "2-s2.0-85105685135", "corpus_eid": "2-s2.0-85105710934", "expected_match": "fuzzy_title",
     "reason": "different papers (depression vs loneliness); fuzzy-title similarity 95.197 (threshold 95)"},
]
CITED_SIMILARITY = re.compile(r"similarity (\d+\.\d{3}) \(threshold")      # a cited score must equal the computed one
TAG_COLS     = ["sdg_number", "source_file", "sdg_tags", "sdg_tag_count"]
KEY_COLS     = ["EID", "DOI", "Title", "Year"]          # Stage 01 Phase 1 key columns
SEP_META     = ["sep_former_kept_eid", "sep_group", "sep_own_sdg_tags", "sep_source_files",
                "sep_source_sha256", "sep_keeper_file", "sep_keeper_row", "sep_anchor_after_eid",
                "sep_anchor_before_eid", "sep_former_kept_own_tags", "sep_former_kept_source_files",
                "sep_fuzzy_score", "sep_abstract_similarity", "sep_reason", "sep_audit_decision"]
ENCODING     = "utf-8-sig"
LINE_END     = "\r\n"
CHUNK_SIZE   = 20_000
FS, RS       = "\x1f", "\x1e"                            # digest field / record separators
R = SimpleNamespace(groups=SEPARATED_GROUPS, own_tags=EXPECTED_OWN_TAGS, deltas=EXPECTED_NON_SDG2_DELTAS,
                    retained=RETAINED_GROUPS, nonmerge=NONMERGE_PAIRS, n_separated=8)


# ── reuse of Stage 01 / Stage 01b code ────────────────────────────────────────
def load_stage01(path: Path = STAGE01_SCRIPT) -> SimpleNamespace:
    """Compile Stage 01 helpers from its own source without running the Stage 01 pipeline."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("clean_title", "merge_sdg_tags")]
    doi = [n for n in tree.body if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == "doi_std" for t in n.targets)]
    eid_if = [n for n in tree.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "eid_col"]
    if len(funcs) != 2 or len(doi) != 2 or len(eid_if) != 1:
        raise RuntimeError(f"{path.name}: helper structure changed; refusing to guess the Stage 01 rules")
    eid = [n for n in eid_if[0].body if isinstance(n, ast.Assign)]
    ns = {"re": re, "pd": pd}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(path), "exec"), ns)  # noqa: S102
    doi_code = compile(ast.Module(body=doi, type_ignores=[]), str(path), "exec")
    eid_code = compile(ast.Module(body=eid, type_ignores=[]), str(path), "exec")

    def run(code, name, s):
        env = {"pd": pd, "df": pd.DataFrame({"_x": s}), f"{name}_col": "_x"}
        exec(code, env)  # noqa: S102
        return env[f"{name}_std"]

    return SimpleNamespace(clean_title=ns["clean_title"], merge_sdg_tags=ns["merge_sdg_tags"],
                           std_doi=lambda s: run(doi_code, "doi", s), std_eid=lambda s: run(eid_code, "eid", s),
                           source_sha256=sha256_file(path))


def load_stage01b(path: Path = STAGE01B_SCRIPT):
    spec = importlib.util.spec_from_file_location("stage01b_scope", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class UnionFind:                                          # same structure as Stage 01
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def fuzzy_edges(titles, years, cut, window):
    """Stage 01 pass-3 comparisons: records with a cleaned title and a numeric year; all pairs within a year,
    all pairs between consecutive present years at most `window` apart; token_set_ratio >= cut."""
    by_year = defaultdict(list)
    for i, (t, y) in enumerate(zip(titles, years)):
        if t and not pd.isna(y):
            by_year[int(y)].append(i)
    ys, edges = sorted(by_year), []
    for y in ys:
        idx = by_year[y]
        if len(idx) > 1:
            s = rf_cdist([titles[i] for i in idx], [titles[i] for i in idx], scorer=fuzz.token_set_ratio,
                         score_cutoff=cut)
            np.fill_diagonal(s, 0)
            edges += [(idx[r], idx[c]) for r, c in zip(*np.where(s > 0)) if r < c]
    for a, b in zip(ys, ys[1:]):
        if b - a <= window:
            A, B = by_year[a], by_year[b]
            s = rf_cdist([titles[i] for i in A], [titles[i] for i in B], scorer=fuzz.token_set_ratio, score_cutoff=cut)
            edges += [(A[r], B[c]) for r, c in zip(*np.where(s > 0))]
    return edges


def resolve_aliases(merge_log: pd.DataFrame, base_eids: set) -> dict:
    """Stage 01 pass-2/3 merges: merged EID -> EID of the record kept in the Stage 01 output (chains followed)."""
    raw = {r: k for p, r, k in zip(merge_log["pass_number"], merge_log["removed_eid"], merge_log["kept_eid"])
           if str(p) in ("2", "3") and r and k and r != k}
    out = {}
    for r, k in raw.items():
        seen = {r}
        while k not in base_eids and k in raw:
            if k in seen:
                raise RuntimeError(f"merged-EID cycle at {k}")
            seen.add(k)
            k = raw[k]
        if k not in base_eids:
            raise RuntimeError(f"merged EID {r} does not resolve to a Stage 01 record ({k})")
        out[r] = k
    return out


def tags_of(s) -> frozenset:
    return frozenset(int(p) for p in str(s).split(",") if p.strip().isdigit())


def tagstr(t) -> str:
    return ",".join(str(n) for n in sorted(t))


# ── SDG 2 assignment (pure; in memory) ────────────────────────────────────────
def sdg2_core(base: pd.DataFrame, sdg2: pd.DataFrame, aliases: dict, S, cut: float, window: int,
              overrides=NONMERGE_PAIRS) -> dict:
    """base: KEY_COLS + sdg_tags (Stage 01 NA semantics). sdg2: SDG 2 export rows, KEY_COLS + part."""
    fails = []
    b_eid = S.std_eid(base["EID"]).tolist()
    b_idx = {e: j for j, e in enumerate(b_eid) if not pd.isna(e)}
    r_eid = S.std_eid(sdg2["EID"]).tolist()
    b_doi, r_doi = S.std_doi(base["DOI"]).tolist(), S.std_doi(sdg2["DOI"]).tolist()
    ov = {(o["sdg2_eid"], o["corpus_eid"]): o for o in overrides}
    r_set = set(r_eid)
    for (re_, me) in ov:
        if re_ not in r_set or me not in b_idx:
            fails.append(f"non-merge pair not present in inputs: {re_} / {me}")
    target, mtype, triggered = {}, {}, {}
    # 1–2: exact EID, then EID merged in Stage 01
    for i, e in enumerate(r_eid):
        if e in b_idx:
            target[i], mtype[i] = e, "exact_eid"
        elif e in aliases:
            target[i], mtype[i] = aliases[e], "merged_eid"
    # 3: exact standardised DOI against corpus records
    doi_to_base = defaultdict(list)
    for e, d in zip(b_eid, b_doi):
        if not pd.isna(d):
            doi_to_base[d].append(e)
    base_dup_doi = {d: es for d, es in doi_to_base.items() if len(es) > 1}
    cand = [i for i in range(len(sdg2)) if i not in target]
    for i in cand:
        d = r_doi[i]
        if pd.isna(d) or d not in doi_to_base:
            continue
        if len(doi_to_base[d]) > 1:
            fails.append(f"{r_eid[i]}: DOI {d} matches several corpus records {doi_to_base[d]}")
            continue
        b = doi_to_base[d][0]
        if (r_eid[i], b) in ov:
            triggered[(r_eid[i], b)] = "doi"
            continue
        target[i], mtype[i] = b, "doi"
    # DOI duplicates among unmatched SDG 2 export records (Stage 01 keeper: more non-null key fields, then lower EID)
    nonnull = sdg2[KEY_COLS].notna().sum(axis=1).tolist()
    merged_new = {}
    rem = [i for i in cand if i not in target]
    groups = defaultdict(list)
    for i in rem:
        if not pd.isna(r_doi[i]):
            groups[r_doi[i]].append(i)
    for members in groups.values():
        if len(members) > 1:
            keep = min(members, key=lambda i: (-nonnull[i], r_eid[i]))
            merged_new.update({m: (keep, "doi") for m in members if m != keep})
    rem = [i for i in rem if i not in merged_new]
    # 4: fuzzy title among records without a DOI (corpus records + remaining SDG 2 export records)
    bnd = [j for j in range(len(base)) if pd.isna(b_doi[j])]
    rnd = [i for i in rem if pd.isna(r_doi[i])]
    nb = len(bnd)
    titles = [S.clean_title(base["Title"].iat[j]) for j in bnd] + [S.clean_title(sdg2["Title"].iat[i]) for i in rnd]
    years = (pd.to_numeric(base["Year"].iloc[bnd], errors="coerce").tolist()
             + pd.to_numeric(sdg2["Year"].iloc[rnd], errors="coerce").tolist())
    eid_at = [b_eid[j] for j in bnd] + [r_eid[i] for i in rnd]
    edges = fuzzy_edges(titles, years, cut, window)
    base_only_pairs = [(eid_at[a], eid_at[b]) for a, b in edges if a < nb and b < nb]
    uf = UnionFind(len(titles))
    for a, b in edges:
        if a < nb and b < nb:
            continue                                   # corpus records are not merged with each other here
        pair = ((eid_at[b], eid_at[a]) if a < nb else (eid_at[a], eid_at[b])) if (a < nb) != (b < nb) else None
        if pair in ov:
            triggered[pair] = "fuzzy_title"
            continue
        uf.union(a, b)
    clusters = defaultdict(list)
    for p in range(len(titles)):
        clusters[uf.find(p)].append(p)
    rank = {e: k for k, e in enumerate(sorted(e for e in r_eid if not pd.isna(e)))}
    for members in clusters.values():
        recs = [m for m in members if m >= nb]
        if not recs or len(members) == 1:
            continue
        bases = [m for m in members if m < nb]
        if len(bases) > 1:
            fails.append(f"fuzzy cluster would merge corpus records {[eid_at[m] for m in bases]} via {[eid_at[m] for m in recs]}")
        elif len(bases) == 1:
            for m in recs:
                target[rnd[m - nb]], mtype[rnd[m - nb]] = eid_at[bases[0]], "fuzzy_title"
        else:
            keep = max(recs, key=lambda m: (nonnull[rnd[m - nb]], -rank[eid_at[m]]))
            merged_new.update({rnd[m - nb]: (rnd[keep - nb], "fuzzy_title") for m in recs if m != keep})
    for (re_, me) in ov:                               # non-merge pairs must stay in different clusters
        if re_ in eid_at and me in eid_at and uf.find(eid_at.index(re_)) == uf.find(eid_at.index(me)):
            fails.append(f"non-merge pair {re_}/{me} connected through another record")
        if any(r_eid[i] == re_ and target.get(i) == me for i in target):
            fails.append(f"non-merge pair {re_}/{me} was merged")
    new = sorted((i for i in range(len(sdg2)) if i not in target and i not in merged_new), key=lambda i: i)
    # SDG 2 tags of corpus records
    supported = defaultdict(list)
    for i, b in target.items():
        supported[b].append((r_eid[i], mtype[i]))
    b_tags = base["sdg_tags"].map(tags_of).tolist()
    changes, deleted, confirmed = {}, [], []
    tags_after = {}                                    # retained corpus records only
    for e, t in zip(b_eid, b_tags):
        after = (t - {2}) | ({2} if e in supported else frozenset())
        if after == t:
            if 2 in t:
                confirmed.append(e)
            tags_after[e] = t
            continue
        if not after:
            deleted.append(e)
        else:
            tags_after[e] = frozenset(after)
        changes[e] = (t, frozenset(after), "added" if 2 in after else ("deleted" if not after else "removed"))
    before_cnt = Counter(g for t in b_tags for g in t)
    after_cnt = Counter(g for t in tags_after.values() for g in t)
    after_cnt[2] += len(new)
    core = {
        "fails": fails, "target": target, "mtype": mtype, "merged_new": merged_new, "new": new,
        "supported": dict(supported), "changes": changes, "deleted": sorted(deleted), "confirmed": sorted(confirmed),
        "triggered": triggered, "base_dup_doi": base_dup_doi, "base_only_fuzzy_pairs": base_only_pairs,
        "sdg_before": dict(before_cnt), "sdg_after": dict(after_cnt), "b_eid": b_eid, "r_eid": r_eid,
        "b_doi": b_doi, "r_doi": r_doi, "tags_after": tags_after,
    }
    core["digest"] = hashlib.sha256(json.dumps({
        "changes": sorted((e, tagstr(a), tagstr(b), k) for e, (a, b, k) in changes.items()),
        "deleted": core["deleted"], "new": sorted(r_eid[i] for i in new),
        "matches": sorted((r_eid[i], b, mtype[i]) for i, b in target.items()),
        "merged_new": sorted((r_eid[i], r_eid[k], how) for i, (k, how) in merged_new.items()),
        "triggered": sorted(f"{a}|{b}|{v}" for (a, b), v in triggered.items())}, sort_keys=True).encode()).hexdigest()
    return core


# ── separated publications (curated fuzzy-title decisions) ────────────────────
def read_checksums(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        h, _, name = line.partition("  ")
        if name.strip():
            out[name.strip()] = h.strip()
    return out


def scan_raw(raw_dir: Path, names, targets: set, checksums: dict, S) -> tuple:
    """Read the 8 May 2026 exports (Stage 01 file order = sorted names; Stage 01 Phase 2 read: utf-8-sig,
    dtype=object, pandas default NA; parsed in chunks, which with dtype=object yields the same cells). Each file is
    hashed from the same bytes it is parsed from. Returns target occurrences, per-file hash records and, for files
    holding a target, the file's standardised EID sequence (row order)."""
    occ, info, seq = defaultdict(list), [], {}
    for fo, name in enumerate(sorted(names)):
        b = (raw_dir / name).read_bytes()
        digest = hashlib.sha256(b).hexdigest()
        sdg = int(FILE_RE.match(name).group(1))
        n, hits, eid_seq = 0, 0, []
        for ch in pd.read_csv(io.BytesIO(b), dtype=object, encoding=ENCODING, chunksize=CHUNK_SIZE):
            eids = S.std_eid(ch["EID"])
            for ri in np.where(eids.isin(targets).to_numpy())[0]:
                occ[eids.iat[ri]].append({"fo": fo, "ri": n + int(ri), "file": name, "sdg": sdg, "row": ch.iloc[ri]})
                hits += 1
            eid_seq += eids.tolist()
            n += len(ch)
        del b
        if hits:
            seq[name] = eid_seq
        info.append({"file": name, "recorded_sha256": checksums.get(name, ""), "computed_sha256": digest,
                     "match": checksums.get(name) == digest, "rows": n, "target_occurrences": hits})
    return occ, info, seq


def stage01_keeper(occurrences: list, S) -> dict:
    """Stage 01 pass-1 keeper inside one exact-EID group: most non-null fields of the Phase 1 frame (EID, DOI,
    Title, Year plus the standardised DOI / EID), then the earliest position (file order, row order)."""
    def nonnull(o):
        r = o["row"]
        sd = S.std_doi(pd.Series([r["DOI"]], dtype=object)).iat[0]
        se = S.std_eid(pd.Series([r["EID"]], dtype=object)).iat[0]
        return sum(not pd.isna(r[c]) for c in KEY_COLS) + (not pd.isna(sd)) + (not pd.isna(se))
    return min(occurrences, key=lambda o: (-nonnull(o), o["fo"], o["ri"]))


def canonical_row(occurrences: list, scopus_cols: list, S) -> tuple:
    """One canonical record per EID, exactly as Stage 01 Phase 2 writes it."""
    keep = stage01_keeper(occurrences, S)
    own = frozenset(o["sdg"] for o in occurrences)
    row = {c: ("" if pd.isna(keep["row"][c]) else str(keep["row"][c])) for c in scopus_cols}
    row.update({"sdg_number": str(keep["sdg"]), "source_file": keep["file"], "sdg_tags": tagstr(own),
                "sdg_tag_count": str(len(own))})
    return row, keep, own


def anchors(seq: list, ri: int, keeper_file: str, base_src: dict) -> tuple:
    """Neighbouring corpus records of the same file block (export order) -> Stage 01 output position."""
    prev = next((e for e in reversed(seq[:ri]) if base_src.get(e) == keeper_file), "")
    nxt = next((e for e in seq[ri + 1:] if base_src.get(e) == keeper_file), "")
    return prev, nxt


def derive_separated(a, R, S, scope, header, base_keys, merge_log, names, extra_targets=()):
    """Canonical export rows of the separated publications, the own SDG tags of the records that had absorbed them,
    and the export files they come from."""
    scopus_cols = [c for c in header if c not in TAG_COLS]
    members = {e: k for k, g in R.groups.items() for e in g["members"]}
    kept_set = set(R.groups)
    checksums = read_checksums(a.raw_checksums)
    occ, info, seq = scan_raw(a.raw_dir, names, set(members) | kept_set | set(extra_targets), checksums, S)
    p3 = merge_log[merge_log["pass_number"] == "3"]
    p3_kept = dict(zip(p3["removed_eid"], p3["kept_eid"]))
    base_src = dict(zip(base_keys["EID"].str.strip(), base_keys["source_file"]))
    base_title = dict(zip(base_keys["EID"].str.strip(), base_keys["Title"]))
    base_doi = set(S.std_doi(base_keys["DOI"].replace("", np.nan)).dropna())
    from utils.country_normalisation import CountryNormaliser
    cn = CountryNormaliser(ARTICLE / "country_lists/country_names_iso2.csv", ARTICLE / "country_lists/au54_countries.csv")
    allowed = {scope.DOCTYPE_LABELS[c] for c in cfg["corpus"]["doc_types"]}
    problems, rows, kept_info = [], [], {}
    for k, g in R.groups.items():
        if not occ.get(k):
            problems.append(f"absorbing record {k} not found in the export files")
            continue
        own_k = frozenset(o["sdg"] for o in occ[k])
        others = [e for e, kk in p3_kept.items() if kk == k and e not in members]   # members that stay merged
        for e in others:
            own_k |= frozenset(o["sdg"] for o in occ.get(e, []))
        krow, kkeep, _ = canonical_row(occ[k], scopus_cols, S)
        kept_info[k] = {"own_tags": own_k, "files": sorted({o["file"] for o in occ[k]}), "row": krow,
                        "members_still_merged": others}
    for k, g in R.groups.items():
        for e in g["members"]:
            if p3_kept.get(e) != k:
                problems.append(f"{e}: Stage 01 pass-3 log does not record a merge into {k}")
            if e in base_src:
                problems.append(f"{e}: already present in the Stage 01 output")
            if not occ.get(e):
                problems.append(f"{e}: not found in the verified export files")
                continue
            row, keep, own = canonical_row(occ[e], scopus_cols, S)
            sd = S.std_doi(pd.Series([keep["row"]["DOI"]], dtype=object)).iat[0]
            if not pd.isna(sd) and sd in base_doi:
                problems.append(f"{e}: DOI {sd} exists in the Stage 01 output (pass-2 merge would apply)")
            prev, nxt = anchors(seq[keep["file"]], keep["ri"], keep["file"], base_src)
            files = sorted({o["file"] for o in occ[e]})
            identical = len({json.dumps({c: str(o["row"][c]) for c in scopus_cols}) for o in occ[e]}) == 1
            k_title = S.clean_title(kept_info.get(k, {}).get("row", {}).get("Title", base_title.get(k, "")))
            score = fuzz.token_set_ratio(S.clean_title(row["Title"]), k_title)
            abs_sim = fuzz.ratio(row["Abstract"][:1500].lower(),
                                 kept_info.get(k, {}).get("row", {}).get("Abstract", "")[:1500].lower())
            elig = scope.eligibility(pd.DataFrame([row]), int(cfg["corpus"]["year_min"]),
                                     int(cfg["corpus"]["year_max"]), allowed).iat[0]
            au = sorted(cn.record(row["Affiliations"]).au)
            row.update({
                "sep_former_kept_eid": k, "sep_group": g["label"], "sep_own_sdg_tags": tagstr(own),
                "sep_source_files": ";".join(files),
                "sep_source_sha256": ";".join(next(x["computed_sha256"] for x in info if x["file"] == f) for f in files),
                "sep_keeper_file": keep["file"], "sep_keeper_row": str(keep["ri"]),
                "sep_anchor_after_eid": prev, "sep_anchor_before_eid": nxt,
                "sep_former_kept_own_tags": tagstr(kept_info[k]["own_tags"]) if k in kept_info else "",
                "sep_former_kept_source_files": ";".join(kept_info[k]["files"]) if k in kept_info else "",
                "sep_fuzzy_score": f"{score:.1f}", "sep_abstract_similarity": f"{abs_sim:.1f}",
                "sep_reason": g["reason"], "sep_audit_decision": "DISTINCT_PUBLICATION"})
            rows.append({"row": row, "identical_occurrences": identical, "in_scope": elig == "" and bool(au), "au": au,
                         "eligibility": elig, "no_doi": pd.isna(sd), "similarity": f"{score:.3f}"})
    rows.sort(key=lambda x: (x["row"]["sep_keeper_file"], int(x["row"]["sep_keeper_row"])))
    return SimpleNamespace(rows=rows, kept=kept_info, info=info, occ=occ, problems=problems, p3=p3)


# ── streaming transform of the Stage 01 output ────────────────────────────────
def stream_output(baseline: Path, header: list, final_changed: dict, deleted: set, separated: pd.DataFrame,
                  new_rows: pd.DataFrame, eligible, out_fh=None) -> dict:
    """Apply final tags / removals chunk by chunk; insert each separated record after its export-order anchor and
    each added SDG 2 record at its source_file position (Stage 01 output order: file name, then row order); compare
    every retained field; digest the output."""
    keep_cols = [c for c in header if c not in ("sdg_tags", "sdg_tag_count")]
    h, st = hashlib.sha256(), Counter()
    first = [True]
    after, at_start = defaultdict(list), defaultdict(list)
    for _, r in separated.iterrows():
        (after[r["sep_anchor_after_eid"]] if r["sep_anchor_after_eid"] else at_start[r["source_file"]]).append(r)
    pending = new_rows.sort_values("source_file", kind="stable")
    state = {"prev_sf": None, "check": None}

    def emit(df, kind):
        if df.empty:
            return
        if kind == "base" and state["check"] is not None:
            exp_eid, exp_sf = state["check"]
            got = df["EID"].iat[0].strip()
            st["anchor_checks"] += 1
            st["anchor_check_fail"] += int(got != exp_eid if exp_eid else df["source_file"].iat[0] == exp_sf)
            state["check"] = None
        for row in df[header].itertuples(index=False, name=None):
            h.update((FS.join(row) + RS).encode("utf-8"))
        st["out_rows"] += len(df)
        st[f"{kind}_emitted"] += len(df)
        st["out_eligible"] += int((eligible(df) == "").sum())
        if out_fh is not None:
            df[header].to_csv(out_fh, header=first[0], index=False, lineterminator=LINE_END)
            first[0] = False
        if kind == "separated":
            last = df.iloc[-1]
            nxt = last["sep_anchor_before_eid"]
            state["check"] = None if nxt in deleted else (nxt, last["source_file"])
            st["anchor_checks_skipped_deleted"] += int(nxt in deleted)

    for chunk in pd.read_csv(baseline, dtype=str, keep_default_na=False, encoding=ENCODING, chunksize=CHUNK_SIZE):
        if list(chunk.columns) != header:
            raise RuntimeError("Stage 01 header changed while streaming")
        st["base_rows"] += len(chunk)
        st["base_eligible"] += int((eligible(chunk) == "").sum())
        eids = chunk["EID"].str.strip()
        keep = ~eids.isin(deleted)
        out = chunk.loc[keep].copy()
        upd = eids[keep].isin(final_changed.keys())
        out.loc[upd, "sdg_tags"] = eids[keep][upd].map(lambda e: tagstr(final_changed[e]))
        out.loc[upd, "sdg_tag_count"] = eids[keep][upd].map(lambda e: str(len(final_changed[e])))
        st["may_field_mismatch"] += int((out[keep_cols].to_numpy() != chunk.loc[keep, keep_cols].to_numpy()).any(axis=1).sum())
        st["unchanged_tag_mismatch"] += int((out.loc[~upd, ["sdg_tags", "sdg_tag_count"]].to_numpy()
                                             != chunk.loc[keep].loc[~upd.to_numpy(), ["sdg_tags", "sdg_tag_count"]].to_numpy()).any(axis=1).sum())
        st["retained"] += int(keep.sum())
        st["tag_rows_changed"] += int(upd.sum())
        sf_arr = out["source_file"].to_numpy()
        kept_upto = np.cumsum(keep.to_numpy())                 # output position after chunk row q = kept_upto[q]
        ins = []
        for q, e in enumerate(eids.to_numpy()):                # anchors are looked up before removal
            if e in after:
                ins.append((int(kept_upto[q]), 1, pd.DataFrame(after.pop(e)), "separated"))
        for sf in list(at_start):
            idx = np.where(sf_arr == sf)[0]
            if len(idx) and (idx[0] > 0 or state["prev_sf"] != sf):
                ins.append((int(idx[0]), 1, pd.DataFrame(at_start.pop(sf)), "separated"))
        while not pending.empty:
            sf = pending["source_file"].iat[0]
            later = np.where(sf_arr > sf)[0]
            if not len(later):
                break
            ins.append((int(later[0]), 0, pending[pending["source_file"] == sf], "new"))
            pending = pending[pending["source_file"] != sf]
        ins.sort(key=lambda x: (x[0], x[1]))
        pos = 0
        for p, _, rows, kind in ins:
            emit(out.iloc[pos:p], "base")
            emit(rows, kind)
            pos = p
        emit(out.iloc[pos:], "base")
        if len(sf_arr):
            state["prev_sf"] = sf_arr[-1]
    if state["check"] is not None:                     # separated record was last of the file: nothing must follow
        st["anchor_checks"] += 1
        st["anchor_check_fail"] += int(bool(state["check"][0]))
    st["anchor_missing"] = sum(len(v) for v in after.values()) + sum(len(v) for v in at_start.values())
    emit(pending, "new")
    st["digest"] = h.hexdigest()
    return dict(st)


# ── main ──────────────────────────────────────────────────────────────────────
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Stage 01a consolidation of the deduplicated corpus")
    for key, default in DEFAULTS.items():
        ap.add_argument(f"--{key.replace('_', '-')}", type=Path, default=default)
    ap.add_argument("--check-only", action="store_true", help="run every step in memory and report; write nothing")
    ap.add_argument("--allow-other-inputs", action="store_true",
                    help="process inputs whose SHA-256 differs from the published analysis (expected results not checked)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing output")
    return ap.parse_args(argv)


def read_keys(source, cols) -> pd.DataFrame:
    """Key columns with Stage 01 semantics (dtype=object, pandas default NA handling)."""
    return pd.read_csv(source, usecols=cols, dtype=object, encoding=ENCODING)[cols]


def consolidate(base, sep_keys, own_tags, sdg2_keys, merge_log, S, cut, window, R):
    """Separated publications + own tags of the absorbing records + SDG 2 assignment, in memory."""
    rb = base.copy()
    fix = rb["EID"].str.strip().isin(own_tags.keys())
    rb.loc[fix, "sdg_tags"] = rb.loc[fix, "EID"].str.strip().map(lambda e: tagstr(own_tags[e]))
    rb = pd.concat([rb, sep_keys[rb.columns]], ignore_index=True)
    separated = set(S.std_eid(sep_keys["EID"]).dropna())
    aliases = {r: k for r, k in resolve_aliases(merge_log, set(S.std_eid(rb["EID"]).dropna())).items()
               if r not in separated}                  # a separated record is no longer an alias of its former group
    core = sdg2_core(rb, sdg2_keys, aliases, S, cut, window, R.nonmerge)
    rb_tags = dict(zip(core["b_eid"], rb["sdg_tags"].map(tags_of)))
    dele = set(core["deleted"])
    final = {e: (core["changes"][e][1] if e in core["changes"] else t) for e, t in rb_tags.items() if e not in dele}
    new_eids = sorted(core["r_eid"][i] for i in core["new"])
    digest = hashlib.sha256(json.dumps({
        "rows": len(final) + len(new_eids), "restored": sorted(sep_keys["EID"]), "deleted": core["deleted"],
        "final_tags": sorted((e, tagstr(t)) for e, t in final.items()), "new": new_eids, "core": core["digest"]},
        sort_keys=True).encode()).hexdigest()
    return SimpleNamespace(core=core, final=final, rb_tags=rb_tags, aliases=aliases, new_eids=new_eids, digest=digest)


def run(a) -> int:
    t0 = datetime.now()
    say = print
    say("=" * 70)
    say(f"STAGE 01a – CONSOLIDATION OF THE DEDUPLICATED CORPUS  v{SCRIPT_VERSION}"
        f"{'  (check only)' if a.check_only else ''}")
    say("=" * 70)
    missing = [str(getattr(a, k)) for k in ("baseline", "sdg2_part1", "sdg2_part2", "merge_log", "raw_checksums")
               if not getattr(a, k).exists()]
    if missing or not a.raw_dir.is_dir():
        say(f"STOP: inputs missing: {missing or [str(a.raw_dir)]}")
        return 2
    published = not a.allow_other_inputs
    hashes = {k: sha256_file(getattr(a, k)) for k in ("baseline", "sdg2_part1", "sdg2_part2")}
    header = pd.read_csv(a.baseline, nrows=0, dtype=str, encoding=ENCODING).columns.tolist()
    r_headers = {k: pd.read_csv(getattr(a, k), nrows=0, dtype=str, encoding=ENCODING).columns.tolist()
                 for k in ("sdg2_part1", "sdg2_part2")}
    S, scope = load_stage01(), load_stage01b()
    base = read_keys(a.baseline, KEY_COLS + ["sdg_tags", "source_file"])
    parts = {k: pd.read_csv(getattr(a, k), dtype=object, encoding=ENCODING) for k in ("sdg2_part1", "sdg2_part2")}
    scopus_cols = [c for c in header if c not in TAG_COLS]
    base_eids = set(base["EID"].dropna().str.strip())
    names = sorted(p.name for p in a.raw_dir.iterdir() if p.is_file() and FILE_RE.match(p.name))
    checks = {
        "Stage 01 output = columns of the exports + sdg_number, source_file, sdg_tags, sdg_tag_count":
            header[-4:] == TAG_COLS and len(scopus_cols) == SCOPUS_COLUMNS,
        "SDG 2 exports have the same columns (names and order)": all(h == scopus_cols for h in r_headers.values()),
        "no EID in both SDG 2 export files": not (set(parts["sdg2_part1"]["EID"]) & set(parts["sdg2_part2"]["EID"])),
        "no duplicate EID within an SDG 2 export file": all(p["EID"].is_unique for p in parts.values()),
        "Stage 01 EIDs unique": base["EID"].dropna().is_unique,
        f"{RAW_FILES} export files of 8 May 2026 present": len(names) == RAW_FILES,
        "output path differs from the Stage 01 output": a.output.resolve() != a.baseline.resolve(),
    }
    if published:
        for k, x in EXPECTED_INPUTS.items():
            n = len(base) if k == "baseline" else len(parts[k])
            checks[f"{k}: SHA-256 and rows = published analysis"] = hashes[k] == x["sha256"] and n == x["rows"]
    for k, v in checks.items():
        say(f"  [{'PASS' if v else 'FAIL'}] {k}")
    if not all(checks.values()):
        say("STOP: input check failed — nothing processed"
            + ("" if a.allow_other_inputs else " (use --allow-other-inputs for other exports)"))
        return 2
    cut = float(cfg["cleaning"]["dedup_title_threshold"]) * 100
    window = int(cfg["cleaning"]["dedup_year_window"])
    say(f"Stage 01 rules reused from {STAGE01_SCRIPT.name}: token_set_ratio >= {cut}, year window {window}")
    merge_log = pd.read_csv(a.merge_log, dtype=str, keep_default_na=False, encoding=ENCODING)
    # ── separated publications: canonical export rows (Stage 01 keeper rule), via an in-memory CSV round trip ──
    bk = pd.read_csv(a.baseline, usecols=["EID", "DOI", "Title", "source_file", "sdg_tags"], dtype=str,
                     keep_default_na=False, encoding=ENCODING)
    p3 = merge_log[merge_log["pass_number"] == "3"]
    D = derive_separated(a, R, S, scope, header, bk, merge_log, names,
                         extra_targets=set(p3["kept_eid"]) | set(p3["removed_eid"]))
    del bk
    sep_csv = io.StringIO()
    pd.DataFrame([r["row"] for r in D.rows])[header + SEP_META].to_csv(sep_csv, index=False, lineterminator=LINE_END)
    sep_text = pd.read_csv(io.StringIO(sep_csv.getvalue()), dtype=str, keep_default_na=False)
    sep_keys = read_keys(io.StringIO(sep_csv.getvalue()), KEY_COLS + ["sdg_tags", "source_file"])
    members = {e: k for k, g in R.groups.items() for e in g["members"]}
    sep_checks = {
        "export files of 8 May 2026: SHA-256 = provenance/stage2_checksums.txt": all(x["match"] for x in D.info),
        "every separated publication found, absent from Stage 01 output, traced to its pass-3 merge": not D.problems,
        f"exactly {R.n_separated} separated publications": len(D.rows) == R.n_separated == len(members),
        "separated publications have no DOI (Stage 01 pass-3 pool)": all(r["no_doi"] for r in D.rows),
        "export rows of each separated publication identical across files": all(r["identical_occurrences"] for r in D.rows),
        "every separated publication eligible (2015-2025, article/review, AU affiliation)": all(r["in_scope"] for r in D.rows),
        "reasons citing a similarity cite the computed value (3 decimals)": all(
            (m := CITED_SIMILARITY.search(r["row"]["sep_reason"])) is None or m.group(1) == r["similarity"]
            for r in D.rows),
    }
    own_tags = {}
    for k in R.groups:
        own = D.kept[k]["own_tags"]
        if own != tags_of(base.loc[base["EID"].str.strip() == k, "sdg_tags"].iat[0]):
            own_tags[k] = own
    sep_checks["absorbing records whose own export tags differ = documented records"] = (
        {k: tagstr(v) for k, v in own_tags.items()} == R.own_tags)
    for p in D.problems:
        say(f"  PROBLEM: {p}")
    for k, v in sep_checks.items():
        say(f"  [{'PASS' if v else 'FAIL'}] {k}")
    if not all(sep_checks.values()):
        say("STOP: separated-publication checks failed — nothing written")
        return 3
    # ── consolidation (twice, for determinism) ──
    sdg2_rows = pd.concat([p.assign(part=k) for k, p in parts.items()], ignore_index=True)
    run1 = consolidate(base, sep_keys, own_tags, sdg2_rows[KEY_COLS], merge_log, S, cut, window, R)
    run2 = consolidate(base, sep_keys, own_tags, sdg2_rows[KEY_COLS], merge_log, S, cut, window, R)
    core = run1.core
    if core["fails"]:
        for f in core["fails"]:
            say(f"  FAIL: {f}")
        say("STOP: a matching rule needs a manual decision — nothing written")
        return 3
    r_eid, mtype, new_idx = core["r_eid"], core["mtype"], core["new"]
    new_rows = sdg2_rows.iloc[new_idx][scopus_cols].copy()
    new_rows["sdg_number"] = "2"
    new_rows["source_file"] = sdg2_rows.iloc[new_idx]["part"].map({"sdg2_part1": a.sdg2_part1.name,
                                                               "sdg2_part2": a.sdg2_part2.name}).to_numpy()
    new_rows["sdg_tags"] = "2"
    new_rows["sdg_tag_count"] = "1"
    new_rows = new_rows.fillna("").astype(str)[header]          # Stage 01 Phase 2: NaN written as ""
    stage01_tags = dict(zip(base["EID"].str.strip(), base["sdg_tags"].map(tags_of)))
    final = run1.final
    deleted = set(core["deleted"])
    sep_set = set(sep_text["EID"])
    final_changed = {e: t for e, t in final.items() if e in stage01_tags and t != stage01_tags[e]}
    sep_rows = sep_text.copy()
    sep_rows["sdg_tags"] = sep_rows["EID"].map(lambda e: tagstr(final[e]))
    sep_rows["sdg_tag_count"] = sep_rows["EID"].map(lambda e: str(len(final[e])))
    sep_rows = sep_rows.sort_values(["sep_keeper_file", "sep_keeper_row"],
                                    key=lambda s: s.astype(int) if s.name == "sep_keeper_row" else s)
    allowed = {scope.DOCTYPE_LABELS[c] for c in cfg["corpus"]["doc_types"]}

    def eligible(df):
        return scope.eligibility(df, int(cfg["corpus"]["year_min"]), int(cfg["corpus"]["year_max"]), allowed)
    out_tmp = None
    if not a.check_only:
        if a.output.exists() and not a.overwrite:
            say(f"STOP: output exists (use --overwrite): {a.output}")
            return 2
        a.output.parent.mkdir(parents=True, exist_ok=True)
        out_tmp = a.output.with_name(a.output.name + ".tmp")
        try:
            with open(out_tmp, "w", encoding=ENCODING, newline="") as fh:
                stream = stream_output(a.baseline, header, final_changed, deleted, sep_rows, new_rows, eligible,
                                       out_fh=fh)
        except BaseException:
            out_tmp.unlink(missing_ok=True)
            raise
    else:
        stream = stream_output(a.baseline, header, final_changed, deleted, sep_rows, new_rows, eligible)
    # ── checks ──
    non2 = [g for g in range(1, 18) if g != 2]
    before = Counter(g for t in stage01_tags.values() for g in t)
    after = Counter(g for t in final.values() for g in t)
    after[2] += len(new_idx)
    delta = {g: after[g] - before[g] for g in non2 if after[g] != before[g]}
    lost_non2 = {e for e, t in final.items() if e in stage01_tags and (stage01_tags[e] - {2}) - t}
    other_changed = {e for e, t in final.items() if e in stage01_tags and e not in own_tags
                     and (t - {2}) != (stage01_tags[e] - {2})}
    supported = core["supported"]
    unsupported2 = [e for e, t in final.items() if 2 in t and e not in supported]
    out_eids = list(final) + run1.new_eids
    out_doi = defaultdict(list)
    for e, d in zip(core["b_eid"], core["b_doi"]):
        if e not in deleted and not pd.isna(d):
            out_doi[d].append(e)
    for i in new_idx:
        if not pd.isna(core["r_doi"][i]):
            out_doi[core["r_doi"][i]].append(r_eid[i])
    dup_doi = {d: es for d, es in out_doi.items() if len(es) > 1}
    ov_pairs = {frozenset((o["sdg2_eid"], o["corpus_eid"])) for o in R.nonmerge}
    unexplained_doi = {d: es for d, es in dup_doi.items() if frozenset(es) not in ov_pairs}
    sep_groups = {frozenset([k] + g["members"]) for k, g in R.groups.items()}
    bo_unexplained = [p for p in core["base_only_fuzzy_pairs"] if not any(set(p) <= g for g in sep_groups)]
    retained_ok = all(k in final and k in stage01_tags and (final[k] - {2}) == (stage01_tags[k] - {2})
                      and k not in sep_set and k not in R.own_tags
                      and not any(x in final or x in run1.new_eids or x in sep_set for x in g["absorbed"])
                      and all(run1.aliases.get(x) == k for x in g["absorbed"]) for k, g in R.retained.items())
    ov_status = {(o["sdg2_eid"], o["corpus_eid"]): core["triggered"].get((o["sdg2_eid"], o["corpus_eid"]), "not triggered")
                 for o in R.nonmerge}
    final_check = {
        "Stage 01 output unchanged while processing": sha256_file(a.baseline) == hashes["baseline"],
        f"{R.n_separated} separated publications inserted at their export-order position":
            stream["separated_emitted"] == R.n_separated and stream["anchor_missing"] == 0
            and stream["anchor_check_fail"] == 0,
        "only the documented absorbing records change non-SDG 2 tags": lost_non2 == set(R.own_tags)
            and not other_changed,
        "change in records per SDG other than SDG 2 = documented": delta == R.deltas,
        "every SDG 2 tag supported by the SDG 2 exports": not unsupported2,
        "fields of every retained Stage 01 record unchanged (except SDG tags)": stream["may_field_mismatch"] == 0
            and stream["unchanged_tag_mismatch"] == 0,
        "added records come only from the SDG 2 exports": stream["new_emitted"] == len(new_idx)
            and not (set(run1.new_eids) & (set(stage01_tags) | sep_set | set(run1.aliases))),
        "three non-merge pairs kept separate": all(v == o["expected_match"] for o, v in zip(R.nonmerge, ov_status.values())),
        "zero duplicate EIDs": len(out_eids) == len(set(out_eids)),
        "duplicate standardised DOIs only for the documented pair": not unexplained_doi,
        "seven retained republication groups unchanged": retained_ok,
        "Stage 01 corpus records are not merged with each other here": not bo_unexplained and not core["base_dup_doi"],
        "determinism (two complete in-memory runs identical)": run1.digest == run2.digest,
        "counts reconcile": stream["out_rows"] == len(final) + len(new_idx) == len(out_eids)
            and stream["tag_rows_changed"] == len(final_changed),
    }
    result = {"consolidated_rows": stream["out_rows"], "eligible_rows": stream["out_eligible"], "removed": len(deleted),
              "added": len(new_idx), "separated": len(sep_set), "sdg2_records": after[2],
              "decision_digest": run1.digest, "output_digest": stream["digest"]}
    if published:
        for k, v in EXPECTED_RESULT.items():
            if v is not None:
                final_check[f"{k} = published analysis ({v})"] = result[k] == v
    mcount = Counter(mtype.values())
    say("\n— COUNTS")
    say(f"  Stage 01 records                 : {stream['base_rows']:,}")
    say(f"  separated publications           : {len(sep_set)}")
    say(f"  SDG 2 export rows                : {len(sdg2_rows):,}  matched to {len(supported):,} corpus records "
        f"(exact EID {mcount['exact_eid']:,} | merged EID {mcount['merged_eid']} | DOI {mcount['doi']} | "
        f"fuzzy title {mcount['fuzzy_title']})")
    say(f"  records added from SDG 2 exports : {len(new_idx):,}   duplicates among them: {len(core['merged_new'])}")
    say(f"  records removed (no SDG left)    : {len(deleted)}")
    say(f"  consolidated records             : {stream['out_rows']:,}   eligible (Stage 01b rules): {stream['out_eligible']:,}")
    say(f"  records tagged SDG 2             : {after[2]:,}")
    say("\n— CHECKS")
    for k, v in final_check.items():
        say(f"  [{'PASS' if v else 'FAIL'}] {k}")
    say(f"\n  decision digest {run1.digest}\n  output digest   {stream['digest']}")
    status = all(final_check.values())
    say(f"\nSTATUS: {'PASS' if status else 'FAIL'}   ({(datetime.now() - t0).total_seconds():.0f}s)")
    if a.check_only:
        say("CHECK ONLY: nothing was written.")
        return 0 if status else 1
    if not status:
        out_tmp.unlink(missing_ok=True)
        say("STOP: a check failed — temporary output removed")
        return 1
    out_sha = sha256_file(out_tmp)
    os.replace(out_tmp, a.output)
    summary = {
        "stage": "01a consolidation of the deduplicated corpus", "script_version": SCRIPT_VERSION,
        "inputs_sha256": {**hashes, "merge_log": sha256_file(a.merge_log)},
        "export_files_8_may_2026": len(names), "parameters": {"title_threshold": cut, "year_window": window},
        "counts": {**{k: v for k, v in result.items() if not k.endswith("digest")},
                   "stage01_records": stream["base_rows"], "sdg2_export_rows": len(sdg2_rows),
                   "sdg2_matches": dict(mcount), "sdg2_duplicates_merged": len(core["merged_new"]),
                   "records_per_sdg": {str(g): after[g] for g in range(1, 18)}},
        "separated_publications": {k: {"label": g["label"], "members": g["members"], "reason": g["reason"]}
                                   for k, g in R.groups.items()},
        "retained_republication_groups": R.retained, "nonmerge_pairs": R.nonmerge,
        "removed_records": sorted(deleted),
        "digests": {"decision": run1.digest, "output_fields": stream["digest"]},
        "output": {"path": a.output.name, "rows": stream["out_rows"], "sha256": out_sha},
        "checks": {k: bool(v) for k, v in {**checks, **sep_checks, **final_check}.items()},
        "environment": {"python": platform.python_version(), "pandas": pd.__version__},
    }
    a.summary.parent.mkdir(parents=True, exist_ok=True)
    a.summary.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    say(f"WRITTEN: {a.output}  ({stream['out_rows']:,} rows, sha256 {out_sha})")
    say(f"SUMMARY: {a.summary}")
    return 0


def main(argv=None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
