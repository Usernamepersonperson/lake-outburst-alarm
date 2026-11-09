"""Figures: docs/figure.png (1600x900) and docs/post-figure.png (960x700, dark)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import data, sim

DOCS = Path(__file__).resolve().parent.parent / "docs"
BG, GRID, TEXT, MUTED = "#16213A", "#2A3750", "#F8FAFC", "#A9B6CB"
ACCENT, GREEN, AMBER, RED, GREY, VIOLET = (
    "#38BDF8",
    "#34D399",
    "#FBBF24",
    "#F87171",
    "#64748B",
    "#A78BFA",
)
EXAMPLE_STATION = "2200"  # Weisse Lutschine, Zweilutschinen
EXAMPLE_NOTE = "Weisse Lutschine, Zweilutschinen, 25 Oct 2026"


def _mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": ["Segoe UI", "DejaVu Sans"],
            "axes.facecolor": BG,
            "figure.facecolor": BG,
            "savefig.facecolor": BG,
            "axes.edgecolor": GRID,
            "axes.labelcolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "text.color": TEXT,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    return plt


def _live_example():
    """Real 10-minute window around the example event, with both alarm times (hours)."""
    live = data.load_live_cache()
    v = live.get(EXAMPLE_STATION)
    if v is None:
        return None
    res = sim.run_live({EXAMPLE_STATION: v})
    ev = max(res["events"], key=lambda e: e["peak_q"])
    t_peak = ev["epoch"]
    sel = (v["epoch"] >= t_peak - 14 * 3600) & (v["epoch"] <= t_peak + 8 * 3600)
    hrs = (v["epoch"][sel] - t_peak) / 3600.0
    t0 = v["t_h"][int(np.argmin(np.abs(v["epoch"] - t_peak)))]
    return {
        "h": hrs,
        "q": v["flow"][sel],
        "det": None if ev["detector_t"] is None else ev["detector_t"] - t0,
        "fix": None if ev["fixed_t"] is None else ev["fixed_t"] - t0,
        "fixed_level": sim.FIXED_FACTOR * ev["ref_q"],
        "lead": ev["lead_h"],
        "peak": ev["peak_q"],
    }


def _panel_event(ax, ex, big=False):
    fs = 12 if big else 12
    ax.plot(ex["h"], ex["q"], color=ACCENT, lw=2.6)
    ax.axhline(ex["fixed_level"], color=GREY, lw=1.8, ls="--")
    ax.text(
        ex["h"][0] + 0.3,
        ex["fixed_level"] * 1.05,
        "fixed level alarm (2.5 x median)",
        color=MUTED,
        fontsize=fs,
        va="bottom",
    )
    if ex["det"] is not None:
        ax.axvline(ex["det"], color=GREEN, lw=2.4)
    if ex["fix"] is not None:
        ax.axvline(ex["fix"], color=RED, lw=2.4)
    ax.set_xlabel("hours relative to the peak", fontsize=fs)
    ax.set_ylabel("discharge (m3/s)", fontsize=fs)
    ax.tick_params(labelsize=fs)
    ax.set_xlim(ex["h"][0], ex["h"][-1])
    ymax = ex["peak"] * 1.28
    ax.set_ylim(0, ymax)
    if ex["det"] is not None and ex["fix"] is not None:
        ax.text(
            ex["det"] - 0.25,
            ymax * 0.92,
            "rate-of-rise\nalarm",
            color=GREEN,
            fontsize=fs,
            ha="right",
            va="top",
            fontweight="bold",
        )
        ax.text(
            ex["fix"] + 0.25,
            ymax * 0.93,
            "fixed-level\nalarm",
            color=RED,
            fontsize=fs,
            ha="left",
            va="top",
            fontweight="bold",
        )


def _lead_curves(res):
    out = {}
    for key, name in (("grid_fixed_2p5x", "2.5x"), ("grid_fixed_4x", "4x")):
        rows = [r for r in res["subdaily_sim"][key] if r["peak_ratio"] == 5.0]
        out[name] = (
            [r["rise_h"] for r in rows],
            [np.nan if r["median_lead_h"] is None else r["median_lead_h"] for r in rows],
        )
    return out


def _panel_lead(ax, res, fs=12):
    cur = _lead_curves(res)
    ax.plot(*cur["2.5x"], color=GREEN, lw=2.8, marker="o", ms=8, label="vs fixed alarm at 2.5x")
    ax.plot(*cur["4x"], color=AMBER, lw=2.8, marker="o", ms=8, label="vs fixed alarm at 4x")
    ax.axhline(0, color=GREY, lw=1.5)
    ax.set_xscale("log")
    ax.set_xticks([2, 6, 12, 24])
    ax.set_xticklabels(["2", "6", "12", "24"])
    ax.minorticks_off()
    ax.set_xlabel("surge rise time (h)", fontsize=fs)
    ax.set_ylabel("earlier warning (h)", fontsize=fs)
    ax.tick_params(labelsize=fs)
    ax.legend(loc="upper left", fontsize=fs, frameon=False, labelcolor=TEXT, handlelength=1.6)
    ax.set_ylim(-1, 8)


def make_main(res: dict, path: Path) -> None:
    plt = _mpl()
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=BG)
    fig.text(
        0.04,
        0.955,
        "Rate-of-rise alarm vs fixed level alarm",
        fontsize=22,
        fontweight="bold",
        va="center",
    )
    fig.text(
        0.04,
        0.915,
        "Real: FOEN/BAFU 10-min (Oct-Nov 2026) and daily (CAMELS-CH, 1981-2020). "
        "Simulated: panel B, D.",
        fontsize=13,
        color=MUTED,
        va="center",
    )
    gs = fig.add_gridspec(
        2, 2, left=0.07, right=0.97, top=0.84, bottom=0.13, hspace=0.55, wspace=0.22
    )
    ax = fig.add_subplot(gs[0, 0])
    ex = _live_example()
    if ex:
        _panel_event(ax, ex)
        ax.set_title(
            f"A  Real 10-min surge: {EXAMPLE_NOTE}",
            loc="left",
            fontsize=14,
            color=TEXT,
            fontweight="bold",
        )
    else:
        ax.text(
            0.5,
            0.5,
            "run `python -m lakealarm fetch` for the live panel",
            ha="center",
            color=MUTED,
            transform=ax.transAxes,
            fontsize=13,
        )
    ax = fig.add_subplot(gs[0, 1])
    _panel_lead(ax, res, 12)
    ax.set_title(
        "B  Simulated 5x surge: median lead over a fixed alarm",
        loc="left",
        fontsize=14,
        color=TEXT,
        fontweight="bold",
    )
    ax = fig.add_subplot(gs[1, 0])
    d = res["daily_real"]
    groups = [
        ("fa_test_2001_2020_glacier_fed", "glacier-fed\n14 stations"),
        ("fa_test_2001_2020_rain_fed", "rain-fed\n6 stations"),
    ]
    x = np.arange(len(groups))
    dry = [d[k]["dry"] / d[k]["station_years"] for k, _ in groups]
    rain = [d[k]["rain_driven"] / d[k]["station_years"] for k, _ in groups]
    ax.bar(x, dry, 0.5, color=AMBER, label="dry-weather alarms")
    ax.bar(x, rain, 0.5, bottom=dry, color=VIOLET, label="rain-driven alarms (real floods)")
    for i in range(len(groups)):
        ax.text(x[i], dry[i] + rain[i] + 0.08, f"{dry[i] + rain[i]:.2f}", ha="center", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels([g[1] for g in groups], fontsize=12)
    ax.set_ylabel("alarms per station-year", fontsize=12)
    ax.tick_params(labelsize=12)
    ax.set_ylim(0, max(np.add(dry, rain)) * 1.45)
    ax.legend(loc="upper left", fontsize=12, frameon=False, labelcolor=TEXT)
    ax.set_title(
        "C  Real daily data, test years 2001-2020",
        loc="left",
        fontsize=14,
        color=TEXT,
        fontweight="bold",
    )
    ax = fig.add_subplot(gs[1, 1])
    e = res["energy_sim"]
    fixed_n = 144.0
    adapt_n = fixed_n * (1 - e["mean_sample_reduction"])
    ax.bar([0, 1], [fixed_n, adapt_n], 0.5, color=[GREY, GREEN])
    ax.text(0, fixed_n + 4, f"{fixed_n:.0f}", ha="center", fontsize=13)
    ax.text(1, adapt_n + 4, f"{adapt_n:.0f}", ha="center", fontsize=13)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["fixed 10 min", "adaptive\n30 min / 5 min when rising"], fontsize=12)
    ax.set_ylabel("samples per day", fontsize=12)
    ax.tick_params(labelsize=12)
    ax.set_ylim(0, 200)
    ax.text(
        0.97,
        0.93,
        f"energy {-e['mean_energy_saving']:+.0%} (assumed costs)\ndetection never later",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=12,
        color=MUTED,
    )
    ax.set_title(
        "D  Simulated 60-day runs: sampling effort",
        loc="left",
        fontsize=14,
        color=TEXT,
        fontweight="bold",
    )
    fig.text(
        0.04,
        0.02,
        "Not an official warning system. Data: FOEN/BAFU; CAMELS-CH (Höge et al., CC BY 4.0).",
        fontsize=11,
        color=MUTED,
    )
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)


def make_post(res: dict, path: Path) -> None:
    plt = _mpl()
    fig = plt.figure(figsize=(9.6, 7.0), dpi=100, facecolor=BG)
    fig.text(
        0.05,
        0.945,
        "Warn on the rise, not on the level",
        fontsize=14.5,
        fontweight="bold",
        va="center",
    )
    fig.text(
        0.05,
        0.9,
        "Real FOEN/BAFU 10-min data (top); simulated surges (bottom)",
        fontsize=11,
        color=MUTED,
        va="center",
    )
    gs = fig.add_gridspec(2, 1, left=0.12, right=0.96, top=0.84, bottom=0.095, hspace=0.62)
    ax = fig.add_subplot(gs[0])
    ex = _live_example()
    if ex:
        _panel_event(ax, ex)
        ax.set_title(f"Real surge, {EXAMPLE_NOTE}", loc="left", fontsize=11.5, color=TEXT)
    ax = fig.add_subplot(gs[1])
    _panel_lead(ax, res, 11.5)
    ax.set_title(
        "Simulated 5x surge: hours of earlier warning", loc="left", fontsize=11.5, color=TEXT
    )
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)


def make_all(res: dict) -> None:
    DOCS.mkdir(exist_ok=True)
    make_main(res, DOCS / "figure.png")
    make_post(res, DOCS / "post-figure.png")
