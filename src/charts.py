"""Static charts for the README (the interactive versions live in the dashboard)."""
import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
FIG = OUT / "figures"

INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
BLUE, QUIET = "#2a78d6", "#b7d3f6"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK, "axes.labelcolor": INK2,
    "axes.edgecolor": AXIS, "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "axes.spines.left": False, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.axisbelow": True, "ytick.major.size": 0, "xtick.major.size": 0,
})


def title(fig, head, sub):
    fig.text(0.06, 0.965, head, fontsize=13, fontweight="bold", ha="left", va="top")
    fig.text(0.06, 0.915, sub, fontsize=9.5, color=INK2, ha="left", va="top")


def rate_distribution(res):
    b = pd.read_csv(OUT / "tables" / "market_rate_buckets.csv")
    names = {"bank": "Banks", "lending_non_bank": "Non-bank lenders still lending",
             "nonlending_non_bank": "Loan owners that no longer lend"}
    fig, axes = plt.subplots(3, 1, figsize=(8, 7.4), sharex=True)
    for ax, (key, name) in zip(axes, names.items()):
        d = b[b.lender_type == key]
        colors = [BLUE if lo >= 4 else QUIET for lo in d.rate_lower]
        ax.bar(d.rate_mid, d.share * 100, width=0.42, color=colors)
        above = d[d.rate_lower >= 4]
        ax.set_title(f"{name}: {above.share.sum() * 100:.0f}% of loans above 4% "
                     f"(about {round(above.accounts.sum(), -3):,.0f} households)", loc="left", fontsize=10, color=INK)
        ax.axvline(res["benchmark_rate_pct"], color=INK2, linewidth=1)
        ax.set_ylabel("% of loans")
        ax.set_ylim(0, 36)
    axes[0].text(res["benchmark_rate_pct"] + 0.08, 32, "Average new fixed rate, 3.46%", fontsize=9, color=INK2)
    axes[-1].set_xlabel("Interest rate on the loan, % (half-point bands)")
    axes[-1].set_xticks(range(0, 10))
    title(fig, "One in four Irish home loans carries a rate above 4%",
          "Share of principal-dwelling mortgages by interest rate, end-June 2026. Source: Central Bank of Ireland.")
    fig.subplots_adjust(top=0.84, hspace=0.42, left=0.09, right=0.97, bottom=0.08)
    fig.savefig(FIG / "rate_distribution.png", dpi=160)
    plt.close(fig)


def switching(con, res):
    s = pd.read_sql("""SELECT quarter, volume FROM bpfi_drawdowns
                       WHERE segment='Re-mortgage/Switching' ORDER BY quarter""", con)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    labels = [f"Q{q[-1]} {q[:4]}" for q in s.quarter]
    ax.bar(labels, s.volume, width=0.45, color=BLUE)
    for x, v in zip(labels, s.volume):
        ax.text(x, v + 30, f"{v:,}", ha="center", fontsize=9, color=INK2)
    ax.set_ylabel("Switching and re-mortgage drawdowns")
    ax.set_ylim(0, 2000)
    title(fig, f"About {res['switches_last_4q']:,} mortgages switched lender in the last year",
          f"That is {res['switch_rate_pct_of_accounts']}% of roughly 700,000 home-loan accounts. Source: BPFI.")
    fig.subplots_adjust(top=0.8, left=0.1, right=0.97, bottom=0.1)
    fig.savefig(FIG / "switching_volumes.png", dpi=160)
    plt.close(fig)


def options(res):
    run_rate = res["run_rate_net_interest_eur_m"]
    o = pd.DataFrame(res["options"])
    o["lost"] = run_rate - o.nii_eur_m
    short = ["A. Status quo: let switchers leave", "B. Cut rates for everyone\n0.5+ points above market",
             "C. Match the market only on\na redemption request"]
    fig, ax = plt.subplots(figsize=(8, 3.9))
    ax.grid(axis="x", color=GRID)
    ax.grid(axis="y", visible=False)
    ax.barh(short[::-1], o.lost[::-1], height=0.4, color=BLUE)
    for y, v in zip(short[::-1], o.lost[::-1]):
        ax.text(v + 0.15, y, f"\u20ac{v:.1f}m", va="center", ha="left", fontsize=9.5, color=INK2)
    ax.set_xlim(0, 14.5)
    ax.set_xlabel("Net interest income given up per year, \u20ac million")
    title(fig, "Cutting rates for everyone costs six times more than losing switchers",
          "Simulated book of 50,000 home loans (\u20ac7.9bn) for a fictional lender; assumptions in the README.")
    fig.subplots_adjust(top=0.76, left=0.36, right=0.97, bottom=0.17)
    fig.savefig(FIG / "bank_options.png", dpi=160)
    plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    res = json.loads((OUT / "results.json").read_text())
    con = sqlite3.connect(OUT / "loyalty_penalty.db")
    rate_distribution(res["market"])
    switching(con, res["market"])
    options(res["bank"])
    con.close()
    print("charts written to", FIG.relative_to(ROOT))


if __name__ == "__main__":
    main()
