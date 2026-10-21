"""Plot a bench/lb.py results directory: p50/p95/p99 of the fast stream per algorithm.

    uv run --with matplotlib python3 bench/plot.py bench/results/<run>/
    uv run --with matplotlib python3 bench/plot.py bench/results/<run>/ --copy-to docs/report/figures/

One PNG per scenario, saved into the results directory. Bars are the median of the repeats,
error bars the min-max.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PERCENTILES = ("p50", "p95", "p99")
COLORS = {"round_robin": "#3b6ea5", "least_conn": "#d9822b", "ip_hash": "#5b8c5a"}
TITLES = {
    "mixed": "Mixed load: latency of the fast requests",
    "slow-replica": "One slow replica: latency of the fast requests",
}


def plot_scenario(scenario: str, algorithms: dict, meta: dict, path: Path) -> None:
    names = list(algorithms)
    width = 0.8 / len(names)
    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=150)
    for i, name in enumerate(names):
        fast = algorithms[name]["fast"]
        stats = [fast[p] for p in PERCENTILES]
        medians = [s["median"] for s in stats]
        errors = [
            [s["median"] - s["min"] for s in stats],
            [s["max"] - s["median"] for s in stats],
        ]
        xs = [x + (i - (len(names) - 1) / 2) * width for x in range(len(PERCENTILES))]
        bars = ax.bar(xs, medians, width * 0.92, yerr=errors, capsize=4,
                      color=COLORS.get(name, "#777777"), label=name, ecolor="#333333")
        for bar, value, top in zip(bars, medians, (s["max"] for s in stats)):
            ax.annotate(f"{value:.0f}", (bar.get_x() + bar.get_width() / 2, top),
                        xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)
    ax.set_xticks(range(len(PERCENTILES)), PERCENTILES)
    ax.set_xlabel("percentile")
    ax.set_ylabel("latency, ms (lower is better)")
    ax.set_title(TITLES.get(scenario, scenario))
    ax.legend(title="algorithm", frameon=False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    note = (f"{meta['repeats']} repeats x {meta['duration']} s; "
            f"{meta['fast_c']} fast x {meta['fast_ms']} ms + {meta['heavy_c']} heavy x {meta['heavy_ms']} ms; "
            "bars: median, whiskers: min-max")
    fig.text(0.5, 0.005, note, ha="center", fontsize=7, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="plot a bench/lb.py results directory")
    parser.add_argument("results", type=Path, help="directory with results.json")
    parser.add_argument("--copy-to", type=Path, help="also copy the PNGs here (e.g. docs/report/figures/)")
    args = parser.parse_args()

    data = json.loads((args.results / "results.json").read_text())
    written = []
    for scenario, algorithms in data["aggregates"].items():
        path = args.results / f"lb-{scenario}.png"
        plot_scenario(scenario, algorithms, data["meta"], path)
        written.append(path)
        print(f"wrote {path}", flush=True)
    if args.copy_to:
        args.copy_to.mkdir(parents=True, exist_ok=True)
        for path in written:
            shutil.copy(path, args.copy_to / path.name)
            print(f"copied to {args.copy_to / path.name}", flush=True)


if __name__ == "__main__":
    main()
