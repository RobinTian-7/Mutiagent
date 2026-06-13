"""Generate the gen-mode aggregate figures (forest plot + strength threshold).

Reads the archived frozen-judge verdict JSONs in lab_records/ and produces:
  docs/figs/gen_forest.png    -- meta-analysis forest plot of gen vs select
                                 and gen vs best-fixed across 9 draws + pooled
  docs/figs/gen_strength.png  -- gen end-strength per draw vs co-beat outcome,
                                 showing the ~50% critical threshold

Run:  uv run --with matplotlib python scripts/plot_gen_aggregate.py
"""
from __future__ import annotations

import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB = os.path.join(os.path.dirname(ROOT), "lab_records")
FIGS = os.path.join(ROOT, "docs", "figs")
os.makedirs(FIGS, exist_ok=True)

# (label, file, kind)  kind picks the arm-key names
DRAWS = [
    ("round-18 (121-128)", "round_18/beats_gen_n5.json", "beats"),
    ("round-21 (131-138)", "round_21/beats_gen_n5.json", "beats"),
    ("round-23 (141-148)", "round_23/beats_gen_n5.json", "beats"),
    ("confirm-2 (RNG)",    "confirmatory_2/beats_gen_n5.json", "beats"),
    ("dev-14 (151-158)",   "round_25/gen_supremacy_n5.json", "sup"),
    ("dev-15 (161-168)",   "round_27/dev15_supremacy_draw2.json", "sup"),
    ("dev-16 (171-178)",   "round_29/dev16_supremacy_draw3.json", "sup"),
    ("dev-17 (181-188)",   "round_31/dev17_supremacy_draw4_PASS.json", "sup"),
    ("dev-18 (191-198)",   "round_32/dev18_supremacy_draw5.json", "sup"),
]


def stats(diffs):
    n = len(diffs)
    m = sum(diffs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in diffs) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    return m * 100, 1.96 * se * 100  # delta_pp, ci95_pp


rows = []          # (label, gen_pct, d_sel, ci_sel, d_fix, ci_fix, both_pass)
all_sel, all_fix = [], []
for label, f, kind in DRAWS:
    p = os.path.join(LAB, f)
    if not os.path.exists(p):
        continue
    d = json.load(open(p))
    gkey = "evolved" if kind == "beats" else "gen"
    fkey = "fixed" if kind == "beats" else "oracle_fixed"
    sel = [pr[gkey] - pr["select"] for pr in d["pairs"]]
    fix = [pr[gkey] - pr[fkey] for pr in d["pairs"]]
    all_sel += sel
    all_fix += fix
    ds, cs = stats(sel)
    df, cf = stats(fix)
    gen_pct = d["arm_means"][gkey] * 100
    pb = d["per_baseline"]
    both = pb["select"]["passed"] and pb[fkey]["passed"]
    rows.append((label, gen_pct, ds, cs, df, cf, both))

pool_sel = stats(all_sel)
pool_fix = stats(all_fix)
n_pairs = len(all_sel)

# ---------- Figure 1: forest plot ----------
fig, axes = plt.subplots(1, 2, figsize=(13, 6), sharey=True)
labels = [r[0] for r in rows]
ys = list(range(len(rows), 0, -1))  # top-down

for ax, (title, col, didx, cidx, pool) in zip(
    axes,
    [("gen − select  (replay-the-best arm)", "#1f6fb4", 2, 3, pool_sel),
     ("gen − best fixed topology", "#b3372b", 4, 5, pool_fix)],
):
    deltas = [r[didx] for r in rows]
    cis = [r[cidx] for r in rows]
    ax.axvspan(-100, 5, color="#f2f2f2", zorder=0)  # below judge line
    ax.axvline(0, color="#999", lw=1)
    ax.axvline(5, color="#1a7f4b", ls="--", lw=1.5, label="+5pp judge line")
    for y, dlt, ci, r in zip(ys, deltas, cis, rows):
        passed = dlt - 0 >= 5  # informal: point clears the line
        c = "#1a7f4b" if dlt >= 5 else "#b3372b"
        ax.errorbar(dlt, y, xerr=ci, fmt="o", color=col, ecolor=col,
                    capsize=3, ms=7, alpha=0.9)
    # pooled diamond
    pm, pci = pool
    ax.errorbar(pm, 0, xerr=pci, fmt="D", color="black", ms=10, capsize=4)
    ax.text(pm, -0.55, f"pooled {pm:+.1f}pp\n(n={n_pairs} pairs)",
            ha="center", va="top", fontsize=9, fontweight="bold")
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("paired delta (percentage points)")
    ax.set_xlim(-30, 45)
    ax.legend(loc="lower right", fontsize=9)

axes[0].set_yticks(ys + [0])
axes[0].set_yticklabels(labels + ["POOLED"])
axes[0].set_ylim(-1.4, len(rows) + 0.6)
fig.suptitle("gen-mode self-evolution vs strongest baselines: 9 independent "
             "draws + pooled (216 paired runs)", fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(os.path.join(FIGS, "gen_forest.png"), dpi=140)
print("wrote docs/figs/gen_forest.png")

# ---------- Figure 2: gen strength threshold ----------
fig2, ax = plt.subplots(figsize=(9, 5))
xs = list(range(len(rows)))
gens = [r[1] for r in rows]
both = [r[6] for r in rows]
cols = ["#1a7f4b" if b else "#b3372b" for b in both]
ax.scatter(xs, gens, c=cols, s=130, zorder=3, edgecolor="black", lw=0.5)
ax.axhline(50, color="#666", ls="--", lw=1.5,
           label="~50% critical threshold")
ax.axhspan(50, 70, color="#e7f4ec", zorder=0)
for x, g in zip(xs, gens):
    ax.annotate(f"{g:.0f}", (x, g), textcoords="offset points",
                xytext=(0, 9), ha="center", fontsize=8)
ax.set_xticks(xs)
ax.set_xticklabels([r[0].split(" ")[0] for r in rows], rotation=40, ha="right")
ax.set_ylabel("gen end-of-evolution exact-match (%)")
ax.set_title("gen strength vs co-beating BOTH select & fixed\n"
             "(green = co-beat both arms; every green sits >=50%)",
             fontsize=12)
from matplotlib.patches import Patch
ax.legend(handles=[
    Patch(color="#1a7f4b", label="co-beat both select & fixed"),
    Patch(color="#b3372b", label="missed >=1 arm"),
    plt.Line2D([0], [0], color="#666", ls="--", label="~50% threshold"),
], loc="lower right", fontsize=9)
ax.set_ylim(28, 68)
fig2.tight_layout()
fig2.savefig(os.path.join(FIGS, "gen_strength.png"), dpi=140)
print("wrote docs/figs/gen_strength.png")
