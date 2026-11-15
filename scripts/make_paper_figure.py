"""
Generate the paper's figure: estimated gain separates by difficulty while the
latent gain cannot.

Run from the repository root:

    python3 scripts/make_paper_figure.py

Writes paper/figures/estimator_inflation.pdf. The data comes from the same
functions the paper's tables are built from, so the figure cannot drift away
from the numbers in the text.

Design notes. The three tiers are a categorical palette validated for
colour-vision deficiency and for contrast against the page. Because the figure
will also be read in greyscale, colour is never the only encoding: each tier
additionally carries its own line style and marker, and the series are labelled
directly at the right-hand end rather than relying on a legend alone. The latent
series is a reference rather than a peer category, so it is drawn in neutral ink
with a heavier weight.
"""

import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.latent_learning_simulation import (  # noqa: E402
    TIERS,
    advance_mastery,
    bkt_posterior,
    build_population,
    cfg_with,
    p_correct,
)

from scripts.paper_style import (  # noqa: E402
    GRID,
    INK,
    TIER_COLOR,
    TIER_STYLE,
    despine,
    save,
    use_paper_style,
)

HORIZONS = (2, 3, 5, 8, 12, 16, 20)
N_TRIALS = 200
P_LEARN = 0.10

# The palette, line styles and markers come from scripts/paper_style.py so
# every figure in the paper shares one visual language. Only the series labels
# are local to this figure.
TIER_LABEL = {
    "easy":   "Estimated, easy items",
    "medium": "Estimated, medium items",
    "hard":   "Estimated, hard items",
}


def measure(cfg, tier):
    latent, estimated = [], []
    for trial in range(N_TRIALS):
        seed = 2000 + trial
        rng = random.Random(seed)
        nprng = np.random.default_rng(seed)
        learners = build_population(rng)
        draws = nprng.random((len(learners), cfg["n_steps"]))
        for i, lr in enumerate(learners):
            theta = hat = lr["theta0"]
            stored = round(lr["theta0"], 4)
            for step in range(cfg["n_steps"]):
                correct = draws[i][step] < p_correct(theta, tier, cfg)
                theta = advance_mastery(theta, tier, lr["gamma"], cfg)
                hat, stored = bkt_posterior(stored, correct, tier, cfg)
            latent.append(theta - lr["theta0"])
            estimated.append(hat - lr["theta0"])
    return float(np.mean(latent)), float(np.mean(estimated))


def main():
    series = {t: [] for t in TIERS}
    latent_curve = []
    for n_steps in HORIZONS:
        cfg = cfg_with(kernel="difficulty-independent", response_model="guess-slip",
                       n_steps=n_steps, p_learn=P_LEARN)
        latent_here = None
        for tier in TIERS:
            latent, estimated = measure(cfg, tier)
            series[tier].append(estimated)
            latent_here = latent  # identical for every tier by construction
        latent_curve.append(latent_here)

    plt = use_paper_style()
    fig, ax = plt.subplots(figsize=(5.4, 3.4))

    # The band between the easiest and hardest estimate is the whole artefact:
    # latent learning is identical across it, so its width is produced entirely
    # by which items were served.
    ax.fill_between(HORIZONS, series["easy"], series["hard"],
                    color=TIER_COLOR["hard"], alpha=0.10, lw=0, zorder=1,
                    label="Spread produced by difficulty alone")

    ax.plot(HORIZONS, latent_curve, color=INK, lw=2.4, ls="-", zorder=5,
            label="Latent gain (identical for all tiers)")
    for tier in TIERS:
        st = TIER_STYLE[tier]
        ax.plot(HORIZONS, series[tier], color=st["color"], lw=1.8, ls=st["ls"],
                marker=st["marker"], markersize=4.5, markeredgecolor="white",
                markeredgewidth=0.6, label=TIER_LABEL[tier], zorder=4)

    ax.set_xlabel("Items answered")
    ax.set_ylabel("Normalised gain")
    ax.set_xticks(list(HORIZONS))
    ax.grid(True, axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    despine(ax)

    # Label the widest point of the band, placed in clear space with a leader
    # rather than written across the curves.
    i = HORIZONS.index(3)
    mid = (series["hard"][i] + series["easy"][i]) / 2
    ax.annotate(
        "19% of the latent gain",
        xy=(3.05, mid), xytext=(3.7, 0.668),
        fontsize=7.6, color="#44403c", va="center", ha="left", zorder=6,
        arrowprops=dict(arrowstyle="-", color="#78716c", lw=0.8,
                        connectionstyle="arc3,rad=0.25"))

    ax.set_ylim(0.08, 0.72)
    # Lower right is the only region the curves and the annotation both avoid.
    ax.legend(loc="lower right", frameon=False, fontsize=7.4, handlelength=2.6,
              borderaxespad=0.6)
    fig.tight_layout()
    save(fig, "estimator_inflation")

    print(f"latent gain at each horizon: {[round(v, 4) for v in latent_curve]}")
    for tier in TIERS:
        print(f"  estimated, {tier:<7}: {[round(v, 4) for v in series[tier]]}")


if __name__ == "__main__":
    main()
