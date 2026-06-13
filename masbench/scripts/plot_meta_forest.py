"""Forest plot for the PRE-REGISTERED N=24 meta-analysis (frozen 575e6093,
unified beats judge). Shows each draw's gen-minus-baseline delta, the
draw-weighted pooled diamond with 95% CI, and -- for contrast -- the biased
11-draw pilot pooled estimate that the unbiased meta overturned.

Run: uv run --with matplotlib python scripts/plot_meta_forest.py
"""
from __future__ import annotations
import json, math, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "runs", "p3_meta")
FIGS = os.path.join(ROOT, "docs", "figs")
os.makedirs(FIGS, exist_ok=True)

draws = [f"{i:02d}" for i in range(1, 25)]
d_fix, d_sel = [], []
for n in draws:
    a = json.load(open(f"{META}/draw{n}/beats/verify_beats_baselines_n5.json"))["arm_means"]
    d_fix.append((a["evolved"] - a["fixed"]) * 100)
    d_sel.append((a["evolved"] - a["select"]) * 100)

def pooled(v):
    n = len(v); m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)

PILOT = {"fixed": 10.86, "select": 5.05}  # biased 11-draw pilot pooled means
fig, axes = plt.subplots(1, 2, figsize=(13, 7), sharey=True)
ys = list(range(len(draws), 0, -1))
for ax, (title, vals, pilot, pm_p) in zip(axes, [
        ("gen − best fixed topology  (H1, powered)", d_fix, PILOT["fixed"], "p=0.73"),
        ("gen − select  (H2, underpowered)", d_sel, PILOT["select"], "p=0.93")]):
    ax.axvspan(-100, 5, color="#f4f4f4", zorder=0)
    ax.axvline(0, color="#888", lw=1)
    ax.axvline(5, color="#1a7f4b", ls="--", lw=1.3, label="+5pp judge line")
    for y, v in zip(ys, vals):
        ax.plot(v, y, "o", color="#b3372b" if v < 5 else "#1a7f4b", ms=6, alpha=0.85)
    pm, pci = pooled(vals)
    ax.errorbar(pm, 0, xerr=pci, fmt="D", color="black", ms=12, capsize=5, zorder=5)
    ax.text(pm, -0.9, f"META pooled {pm:+.1f}pp\n(N=24, {pm_p})", ha="center",
            va="top", fontsize=9, fontweight="bold")
    ax.plot(pilot, -2.4, "v", color="#c77", ms=11)
    ax.text(pilot, -3.0, f"biased pilot\n{pilot:+.1f}pp", ha="center", va="top",
            fontsize=8, color="#a55", style="italic")
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("paired delta (percentage points)")
    ax.set_xlim(-45, 45)
    ax.legend(loc="lower right", fontsize=9)
axes[0].set_yticks(ys + [0])
axes[0].set_yticklabels([f"draw{n}" for n in draws] + ["META"])
axes[0].set_ylim(-3.6, len(draws) + 0.6)
fig.suptitle("Pre-registered N=24 meta-analysis: gen does NOT beat the strongest "
             "fixed topology or select\n(unbiased meta overturns the biased 11-draw "
             "pilot; coldgen still dominated +26.6pp, not shown)",
             fontsize=12.5, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(os.path.join(FIGS, "meta_forest_n24.png"), dpi=140)
print("wrote docs/figs/meta_forest_n24.png")
