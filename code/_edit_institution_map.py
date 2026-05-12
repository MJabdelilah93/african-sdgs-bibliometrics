import pandas as pd
import numpy as np

BASE = r"c:\Users\AbdelilahElMajjaoui\Downloads\PhD\Article 8\african_sdgs\article08\figures"
MAP_IN  = BASE + r"\network_institution_map.txt"
NET_IN  = BASE + r"\network_institution_network.txt"
MAP_OUT = BASE + r"\network_institution_map_clean.txt"
NET_OUT = BASE + r"\network_institution_network_clean.txt"

# ── Load ──────────────────────────────────────────────────────────────────────
map_df = pd.read_csv(MAP_IN, sep="\t", dtype={"id": int})
net_df = pd.read_csv(NET_IN, sep="\t", header=None,
                     names=["from_id", "to_id", "weight"],
                     dtype={"from_id": int, "to_id": int, "weight": int})

# ── STEP 1: Print id + label ──────────────────────────────────────────────────
print("=== STEP 1: ALL IDs AND LABELS ===")
for _, r in map_df.iterrows():
    print(f"  {r['id']:>7}  {r['label']}")
print(f"\nTotal nodes: {len(map_df)}")
print(f"Total edges: {len(net_df)}")

# ── STEP 2: Merges ────────────────────────────────────────────────────────────
MERGES = [
    (784065, 784264, "University of Cape Town"),
    (788377, 788439, "University of Johannesburg"),
    (796561, 796658, "University of the Witwatersrand"),
    (719475, 720512, "Univ. of the Witwatersrand (SPH)"),
]

print("\n=== STEP 2: MERGES ===")
for keep_id, absorb_id, new_label in MERGES:
    old_keep_label   = map_df.loc[map_df["id"] == keep_id,   "label"].values[0]
    old_absorb_label = map_df.loc[map_df["id"] == absorb_id, "label"].values[0]

    # Edges involving the absorbed node before redirect
    edges_from = (net_df["from_id"] == absorb_id).sum()
    edges_to   = (net_df["to_id"]   == absorb_id).sum()
    total_redirected = edges_from + edges_to

    # Redirect absorbed → keep
    net_df["from_id"] = net_df["from_id"].replace(absorb_id, keep_id)
    net_df["to_id"]   = net_df["to_id"].replace(absorb_id, keep_id)

    # Remove self-loops
    net_df = net_df[net_df["from_id"] != net_df["to_id"]].copy()

    # Normalise so lower ID is always 'from'
    mask = net_df["from_id"] > net_df["to_id"]
    net_df.loc[mask, ["from_id", "to_id"]] = (
        net_df.loc[mask, ["to_id", "from_id"]].values
    )

    # Sum weights on duplicate edges
    net_df = (net_df.groupby(["from_id", "to_id"], as_index=False)["weight"]
              .sum())

    # Update keep node label; remove absorbed node
    map_df.loc[map_df["id"] == keep_id, "label"] = new_label
    map_df = map_df[map_df["id"] != absorb_id].copy()

    print(f"\n  Merge: {keep_id} + {absorb_id}")
    print(f"    Keep:    {old_keep_label}")
    print(f"    Absorb:  {old_absorb_label}")
    print(f"    New label: {new_label}")
    print(f"    Edges redirected: {total_redirected}")

print(f"\n  Nodes after merges : {len(map_df)}")
print(f"  Edges after merges : {len(net_df)}")

# ── STEP 3: Label replacements ────────────────────────────────────────────────
LABEL_MAP = {
    9062:   "African Population & Health Research Center",
    185362: "Liverpool Sch. of Tropical Medicine (Clinical)",
    220930: "University of Gondar",
    223114: "University of Washington (Epidemiology)",
    240371: "LSHTM (Global Health & Development)",
    240525: "Harvard T.H. Chan School of Public Health",
    241204: "University of Washington (Global Health)",
    241355: "Karolinska Institutet",
    257451: "Johns Hopkins Bloomberg School of Public Health",
    326258: "University of Cape Coast",
    329358: "University of Cape Town (Psychiatry)",
    412718: "Ethiopian Public Health Institute",
    470100: "Harvard Medical School",
    503312: "University College London (Global Health)",
    527383: "International Livestock Research Institute",
    540426: "Kenya Medical Research Institute",
    546469: "KNUST",
    583576: "Liverpool School of Tropical Medicine",
    584789: "London School of Hygiene & Tropical Medicine",
    637467: "North-West University",
    718743: "Addis Ababa University (Public Health)",
    719475: "Univ. of the Witwatersrand (SPH)",
    748972: "Swiss Tropical and Public Health Institute",
    782348: "University of Basel",
    784065: "University of Cape Town",
    788377: "University of Johannesburg",
    789297: "University of KwaZulu-Natal",
    793553: "University of Pretoria",
    795175: "University of South Africa",
    796561: "University of the Witwatersrand",
    821042: "World Health Organization",
}

print("\n=== STEP 3: LABEL REPLACEMENTS ===")
changed = 0
for node_id, new_lbl in LABEL_MAP.items():
    row = map_df[map_df["id"] == node_id]
    if row.empty:
        print(f"  WARNING: id {node_id} not found in map (already absorbed)")
        continue
    old_lbl = row["label"].values[0]
    if old_lbl != new_lbl:
        map_df.loc[map_df["id"] == node_id, "label"] = new_lbl
        print(f"  {node_id:>7}: {old_lbl[:60]}")
        print(f"          -> {new_lbl}")
        changed += 1
    else:
        print(f"  {node_id:>7}: (already correct) {new_lbl}")
print(f"\n  Labels changed: {changed}")

# ── STEP 4: Spread coordinates ────────────────────────────────────────────────
print("\n=== STEP 4: COORDINATE SPREADING ===")

def scale_from_centroid(df, mask, factor):
    cx = df.loc[mask, "x"].mean()
    cy = df.loc[mask, "y"].mean()
    df.loc[mask, "x"] = cx + factor * (df.loc[mask, "x"] - cx)
    df.loc[mask, "y"] = cy + factor * (df.loc[mask, "y"] - cy)
    return df, cx, cy

# Cluster 1
c1 = map_df["cluster"] == 1
xr1b = (map_df.loc[c1, "x"].min(), map_df.loc[c1, "x"].max())
yr1b = (map_df.loc[c1, "y"].min(), map_df.loc[c1, "y"].max())
map_df, cx1, cy1 = scale_from_centroid(map_df, c1, 4.0)
xr1a = (map_df.loc[c1, "x"].min(), map_df.loc[c1, "x"].max())
yr1a = (map_df.loc[c1, "y"].min(), map_df.loc[c1, "y"].max())
print(f"  Cluster 1 (n={c1.sum()}, factor=4.0):")
print(f"    x before: [{xr1b[0]:.4f}, {xr1b[1]:.4f}]  after: [{xr1a[0]:.4f}, {xr1a[1]:.4f}]")
print(f"    y before: [{yr1b[0]:.4f}, {yr1b[1]:.4f}]  after: [{yr1a[0]:.4f}, {yr1a[1]:.4f}]")

# Cluster 2 — sort by x, assign evenly-spaced x (0.15 apart) and y (-0.6 to 0.6)
c2 = map_df["cluster"] == 2
xr2b = (map_df.loc[c2, "x"].min(), map_df.loc[c2, "x"].max())
yr2b = (map_df.loc[c2, "y"].min(), map_df.loc[c2, "y"].max())
idx2 = map_df[c2].sort_values("x").index
n2 = len(idx2)
new_x2 = [1.40 + i * 0.15 for i in range(n2)]
new_y2 = np.linspace(-0.6, 0.6, n2).tolist()
map_df.loc[idx2, "x"] = new_x2
map_df.loc[idx2, "y"] = new_y2
xr2a = (map_df.loc[c2, "x"].min(), map_df.loc[c2, "x"].max())
yr2a = (map_df.loc[c2, "y"].min(), map_df.loc[c2, "y"].max())
print(f"  Cluster 2 (n={n2}, evenly-spaced x+y):")
print(f"    x before: [{xr2b[0]:.4f}, {xr2b[1]:.4f}]  after: [{xr2a[0]:.4f}, {xr2a[1]:.4f}]")
print(f"    y before: [{yr2b[0]:.4f}, {yr2b[1]:.4f}]  after: [{yr2a[0]:.4f}, {yr2a[1]:.4f}]")

# Cluster 3
c3 = map_df["cluster"] == 3
map_df, _, _ = scale_from_centroid(map_df, c3, 3.0)
print(f"  Cluster 3 (n={c3.sum()}, factor=3.0): spread applied")

# Cluster 4
c4 = map_df["cluster"] == 4
map_df, _, _ = scale_from_centroid(map_df, c4, 3.0)
print(f"  Cluster 4 (n={c4.sum()}, factor=3.0): spread applied")

# Cluster 5 — no change
c5 = map_df["cluster"] == 5
print(f"  Cluster 5 (n={c5.sum()}): no change")

# ── STEP 5: Write output ──────────────────────────────────────────────────────
map_df.to_csv(MAP_OUT, sep="\t", index=False, float_format="%.4f")
net_df.to_csv(NET_OUT, sep="\t", index=False, header=False)

ms = __import__("os").path.getsize(MAP_OUT)
ns = __import__("os").path.getsize(NET_OUT)

print("\n=== STEP 5: OUTPUT FILES ===")
print(f"  {MAP_OUT}")
print(f"    Rows: {len(map_df)}  Size: {ms:,} bytes")
print(f"  {NET_OUT}")
print(f"    Rows: {len(net_df)}  Size: {ns:,} bytes")

print("\n=== SUMMARY ===")
print(f"  Merges performed    : {len(MERGES)}")
print(f"  Labels changed      : {changed}")
print(f"  Nodes remaining     : {len(map_df)}")
print(f"  Edges remaining     : {len(net_df)}")
print("  Done.")
