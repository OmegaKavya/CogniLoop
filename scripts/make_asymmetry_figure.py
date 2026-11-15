"""Generate the mis-routing asymmetry figure.

Run from the repository root:

    python3 scripts/make_asymmetry_figure.py

Writes paper/figures/misrouting_asymmetry.pdf.

What it shows
-------------
Section 6's result, which is the paper's most nuanced claim and the one most
worth making impossible to misread: serving one tier too hard is far more
costly than serving one tier too easy under two of the three learning-model
specifications, and under the third the asymmetry weakens and reverses.

The table states this, but a reader has to work across six rows of signed
percentages to see the reversal. Here model C's bars visibly swap sides.

Presenting the reversal prominently rather than burying it is deliberate. A
reviewer who discovers a direction-flip the paper glossed over will discount
everything else in it; a paper that draws its own exception is making a
narrower claim it can defend - that erring easy is the *minimax* choice, not
the universally better one.

Numbers come from the same computation as Table 3: the identical seeds,
population and per-step optimal-tier rule as `misrouting_cost`. Because that
function prints rather than returns, the measurement loop is reproduced here
and asserted against the published table at the end of the run, so the figure
cannot silently drift from the text.
"""

import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.latent_learning_simulation import (  # noqa: E402
    MODEL_SPECS,
    TIERS,
    advance_mastery,
    build_population,
    cfg_with,
    learning_kernel,
)
from scripts.paper_style import (  # noqa: E402
    GRID,
    INK,
    MUTED,
    TIER_COLOR,
    despine,
    save,
    use_paper_style,
)

HORIZONS = (6, 24)
N_TRIALS = 150

MODEL_LABEL = {
    "A": "A\ntarget,\nguess/slip",
    "B": "B\ntarget,\nIRT",
    "C": "C\ndifficulty\nmatching",
}

# The direction of the error is encoded with the tier colours used everywhere
# else in the paper: teal is the easy tier, violet the hard one. A reader who
# has seen Figures 1 and 2 does not have to relearn the mapping.
DIRECTION = {
    -1: {"color": TIER_COLOR["easy"], "label": "Served one tier too easy"},
    +1: {"color": TIER_COLOR["hard"], "label": "Served one tier too hard"},
}

# Published in Table 3; the run asserts against these so figure and table
# cannot diverge.
PUBLISHED = {
    (6, "A"): (-0.0, -74.9), (6, "B"): (-0.9, -89.0), (6, "C"): (-29.2, -23.7),
    (24, "A"): (-0.2, -45.9), (24, "B"): (-0.5, -77.5), (24, "C"): (-14.7, -1.5),
}


def mean_gain(cfg, offset):
    """Mean normalised gain when every item is `offset` tiers from optimal."""
    gains = []
    for trial in range(N_TRIALS):
        seed = 4000 + trial
        rng = random.Random(seed)
        nprng = np.random.default_rng(seed)
        learners = build_population(rng)
        nprng.random((len(learners), cfg["n_steps"]))
        for learner in learners:
            theta = learner["theta0"]
            for _ in range(cfg["n_steps"]):
                best = max(range(len(TIERS)),
                           key=lambda j: learning_kernel(theta, TIERS[j], cfg))
                tier = TIERS[min(len(TIERS) - 1, max(0, best + offset))]
                theta = advance_mastery(theta, tier, learner["gamma"], cfg)
            gains.append(theta - learner["theta0"])
    return float(np.mean(gains))


def measure():
    results = {}
    for n_steps in HORIZONS:
        for name, overrides in MODEL_SPECS:
            cfg = cfg_with(**overrides, n_steps=n_steps)
            optimal = mean_gain(cfg, 0)
            results[(n_steps, name)] = tuple(
                100.0 * (mean_gain(cfg, off) - optimal) / optimal
                for off in (-1, +1))
    return results


def main():
    results = measure()

    # Fail loudly rather than publish a figure that disagrees with the table.
    for key, (too_easy, too_hard) in results.items():
        want_easy, want_hard = PUBLISHED[key]
        assert abs(too_easy - want_easy) < 0.15, (key, too_easy, want_easy)
        assert abs(too_hard - want_hard) < 0.15, (key, too_hard, want_hard)
    print("figure matches Table 3 for all six cells")

    plt = use_paper_style()
    fig, axes = plt.subplots(1, 2, figsize=(6.0, 3.1), sharey=True)

    names = [name for name, _ in MODEL_SPECS]
    x = np.arange(len(names))
    width = 0.34

    for ax, n_steps in zip(axes, HORIZONS):
        for k, offset in enumerate((-1, +1)):
            # Plotted as loss magnitude: every value is a shortfall, and a
            # chart of negative bars hanging below an axis is harder to compare
            # than one of positive bars measured from it.
            heights = [-results[(n_steps, name)][k] for name in names]
            bars = ax.bar(x + (k - 0.5) * width, heights, width,
                          color=DIRECTION[offset]["color"],
                          label=DIRECTION[offset]["label"],
                          edgecolor="white", linewidth=0.8, zorder=3)
            for rect, value in zip(bars, heights):
                ax.text(rect.get_x() + rect.get_width() / 2,
                        rect.get_height() + 1.6, f"{value:.0f}%",
                        ha="center", va="bottom", fontsize=6.9, color=MUTED,
                        zorder=5)

        ax.set_title(f"{n_steps} items", fontsize=8.6, color=INK, pad=6)
        ax.set_xticks(x)
        ax.set_xticklabels([MODEL_LABEL[n] for n in names], fontsize=7.2)
        ax.grid(True, axis="y", color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        despine(ax)
        ax.set_ylim(0, 100)

    axes[0].set_ylabel("Attainable gain lost (%)")

    # One legend for both panels, placed above them so neither panel's bars
    # have to make room for it.
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False,
               fontsize=7.6, bbox_to_anchor=(0.5, 1.06))

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save(fig, "misrouting_asymmetry")

    for n_steps in HORIZONS:
        print(f"\n  horizon {n_steps} items")
        for name in names:
            easy, hard = results[(n_steps, name)]
            print(f"    {name}: too easy {easy:6.1f}%   too hard {hard:6.1f}%")


if __name__ == "__main__":
    main()
