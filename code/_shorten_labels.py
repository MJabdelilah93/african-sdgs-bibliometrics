import re
import pandas as pd
from collections import Counter

MAP_FILE = (r"c:\Users\AbdelilahElMajjaoui\Downloads\PhD\Article 8"
            r"\african_sdgs\article08\figures\network_institution_map_clean.txt")

df = pd.read_csv(MAP_FILE, sep="\t", dtype={"id": int})

SUFFIXES = [
    ", south africa", ", kenya", ", ethiopia", ", ghana",
    ", switzerland", ", united kingdom", ", united states",
    ", sweden", ", london", ", nairobi", ", addis ababa",
    ", johannesburg", ", cape town", ", basel",
]

RULE4 = {
    "london school of hygiene & tropical medicine":     "LSHTM",
    "london school of hygiene and tropical medicine":   "LSHTM",
    "liverpool school of tropical medicine":            "Liverpool STM",
    "liverpool sch. of tropical medicine":              "Liverpool STM",
    "johns hopkins bloomberg school of public health":  "Johns Hopkins BSPH",
    "harvard t.h. chan school of public health":        "Harvard Chan SPH",
    "harvard medical school":                           "Harvard Medical School",
    "swiss tropical and public health institute":       "Swiss TPH",
    "international livestock research institute":       "ILRI",
    "kenya medical research institute":                 "KEMRI",
    "world health organization":                        "WHO",
    "african population & health research center":      "APHRC",
    "kwame nkrumah univ. of science and technology":    "KNUST",
    "univ. of kwazulu-natal":                           "UKZN",
    "univ. of the witwatersrand":                       "Univ. of Witwatersrand",
    "north-west univ.":                                 "North-West Univ.",
    "stellenbosch univ.":                               "Stellenbosch Univ.",
    "univ. of cape town":                               "Univ. of Cape Town",
    "univ. of johannesburg":                            "Univ. of Johannesburg",
    "univ. of pretoria":                                "Univ. of Pretoria",
    "univ. of south africa":                            "UNISA",
    "univ. of cape coast":                              "Univ. of Cape Coast",
    "univ. of gondar":                                  "Univ. of Gondar",
    "univ. of basel":                                   "Univ. of Basel",
    "univ. of washington":                              "Univ. of Washington",
    "ethiopian public health institute":                "Ethiopian PHI",
    "karolinska institutet":                            "Karolinska Institutet",
    "addis ababa univ.":                                "Addis Ababa Univ.",
    "univ. college london":                             "UCL",
    "university college london":                        "UCL",
}


def apply_rules(label):
    s = label.strip()

    # Rule 1 — remove parenthetical suffixes
    s = re.sub(r'\s*\([^)]*\)', '', s).strip()

    # Rule 2 — University -> Univ. (case-insensitive to handle all-lowercase labels)
    s = re.sub(r'\bUniversity\b',   'Univ.',  s, flags=re.IGNORECASE)
    s = re.sub(r'\bUniversities\b', 'Univs.', s, flags=re.IGNORECASE)

    # Rule 3 — trailing country/city suffixes (case-insensitive)
    sl = s.lower()
    for suf in SUFFIXES:
        if sl.endswith(suf):
            s  = s[:len(s) - len(suf)].strip()
            sl = s.lower()

    # Rule 4 — known short forms (case-insensitive key lookup)
    # Also capitalise first letter so all-lowercase labels get proper casing
    if s.lower() in RULE4:
        s = RULE4[s.lower()]
    elif s and s[0].islower():
        s = s[0].upper() + s[1:]

    # Rule 5 — truncate to 30 chars at word boundary
    if len(s) > 30:
        words  = s.split()
        result = ""
        for word in words:
            candidate = (result + " " + word).strip()
            if len(candidate) <= 30:
                result = candidate
            else:
                break
        s = result

    return s


old_labels = df["label"].tolist()
new_labels = [apply_rules(lbl) for lbl in old_labels]

# ── Report table sorted by new_length descending ──────────────────────────────
rows = list(zip(df["id"].tolist(), old_labels, new_labels,
                [len(n) for n in new_labels]))
rows.sort(key=lambda r: r[3], reverse=True)

print(f"\n{'id':>7}  {'old_label':<48}  {'new_label':<25}  len")
print("-" * 95)
for iid, old, new, ln in rows:
    flag = "  *** >30" if ln > 30 else ""
    print(f"{iid:>7}  {old[:48]:<48}  {new:<25}  {ln:>3}{flag}")

# ── Duplicate check ────────────────────────────────────────────────────────────
dupes = {lbl: [] for lbl, cnt in Counter(new_labels).items() if cnt > 1}
for i, lbl in enumerate(new_labels):
    if lbl in dupes:
        dupes[lbl].append(int(df["id"].iloc[i]))

print(f"\n{'='*60}")
if dupes:
    print(f"WARNING: {len(dupes)} duplicate label(s) after shortening:")
    for lbl, ids in dupes.items():
        print(f"  '{lbl}'  ->  ids: {', '.join(str(x) for x in ids)}")
else:
    print("No duplicate labels detected.")

# ── Write output ───────────────────────────────────────────────────────────────
df["label"] = new_labels
df.to_csv(MAP_FILE, sep="\t", index=False, float_format="%.4f")

import os
sz = os.path.getsize(MAP_FILE)
print(f"\nSaved: {MAP_FILE}")
print(f"  Rows: {len(df)}  Size: {sz:,} bytes")
print("Done.")
