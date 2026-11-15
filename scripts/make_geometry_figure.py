"""Generate the tier-geometry figure.

Run from the repository root:

    python3 scripts/make_geometry_figure.py

Writes paper/figures/tier_geometry.pdf.

What it shows
-------------
This is the paper's Section 4 result drawn rather than tabulated. Each tier's
response curve P(correct | theta) is plotted against mastery, together with the
target success rate P* and the mastery theta*_d at which each tier sits exactly
on that target.

The argument the figure has to make visible is that the three theta*_d lie
close together and close to ceiling: over the mastery range a cohort actually
occupies during instruction, the optimal tier does not change, so an adaptive
policy has nothing to adapt to. In the table this is six numbers; here it is
the width of the shaded band.

The curves and the crossing points come from the same functions the table is
computed from, so the figure cannot drift away from the numbers in the text.
Nothing here is simulated - it is Equation 1 and Equation 2 evaluated directly.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.latent_learning_simulation import (  # noqa: E402
    TIERS,
    cfg_with,
    p_correct,
)
from scripts.paper_style import (  # noqa: E402
    GRID,
    INK,
    MUTED,
    TIER_STYLE,
    despine,
    save,
    use_paper_style,
)

LABEL = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}


def theta_star(tier, cfg):
    """Mastery at which `tier` sits exactly at the target success rate.

    Equation 2 of the paper. Returns None when the tier's maximum attainable
    accuracy (1 - s) is below the target, in which case it never reaches it.
    """
    g, s = cfg["guess"][tier], cfg["slip"][tier]
    denominator = (1.0 - s) - g
    if denominator <= 0:
        return None
    value = (cfg["p_star"] - g) / denominator
    return value if 0.0 <= value <= 1.0 else None


def main():
    plt = use_paper_style()
    cfg = cfg_with(response_model="guess-slip")
    p_star = cfg["p_star"]

    theta = np.linspace(0.0, 1.0, 400)
    stars = {t: theta_star(t, cfg) for t in TIERS}

    fig, ax = plt.subplots(figsize=(5.4, 3.5))

    # The band spanning the tiers' optimal operating points is the whole
    # argument: its narrowness is what leaves an adaptive policy nothing to do.
    present = [v for v in stars.values() if v is not None]
    lo, hi = min(present), max(present)
    ax.axvspan(lo, hi, color="#6D28D9", alpha=0.07, lw=0, zorder=1)

    # Target success rate: a reference, so neutral ink rather than a tier hue.
    ax.axhline(p_star, color=INK, lw=1.1, ls=(0, (4, 3)), zorder=3)
    ax.text(0.015, p_star + 0.012, f"Target success rate $P^*={p_star:g}$",
            fontsize=7.6, color=INK, va="bottom", ha="left", zorder=6)

    for tier in TIERS:
        st = TIER_STYLE[tier]
        curve = [p_correct(x, tier, cfg) for x in theta]
        ax.plot(theta, curve, color=st["color"], lw=1.9, ls=st["ls"],
                zorder=4, label=f"{LABEL[tier]} tier")

        star = stars[tier]
        if star is not None:
            # Drawn with clip_on disabled so the hard tier's marker, which sits
            # exactly on the axis limit at theta = 1, is not cut in half.
            ax.plot([star], [p_star], marker=st["marker"], markersize=6.5,
                    color=st["color"], markeredgecolor="white",
                    markeredgewidth=0.9, zorder=7, linestyle="none",
                    clip_on=False)

    # The hard tier's ceiling equalling P* exactly is stated in the caption and
    # in the body text. Annotating it here as well meant writing a two-line
    # label and its leader across the medium and hard curves, which cost more
    # legibility than the repetition was worth.

    ax.set_xlabel(r"Mastery $\theta$")
    ax.set_ylabel(r"$P(\mathrm{correct} \mid \theta)$")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xticks(np.arange(0.0, 1.01, 0.2))
    ax.set_yticks(np.arange(0.0, 1.01, 0.2))
    ax.grid(True, axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    despine(ax)

    # The theta*_d values go on a secondary axis rather than beside the markers.
    # Placed in the plot area they collided with each other and with the curves;
    # as ticks they read cleanly and stay tied to the mastery scale.
    secondary = ax.secondary_xaxis("top")
    secondary.set_xticks([v for v in (stars[t] for t in TIERS) if v is not None])
    secondary.set_xticklabels(
        [f"{stars[t]:.3f}" for t in TIERS if stars[t] is not None], fontsize=6.8)
    secondary.set_xlabel(r"$\theta^{*}_d$: mastery at which each tier meets $P^{*}$",
                         fontsize=7.4, labelpad=4)
    secondary.tick_params(axis="x", length=3, color=MUTED, pad=2)
    for label, tier in zip(secondary.get_xticklabels(),
                           [t for t in TIERS if stars[t] is not None]):
        label.set_color(TIER_STYLE[tier]["color"])

    # Lower right is clear: every curve is rising toward the top right, and the
    # annotations sit centre and upper left.
    ax.legend(loc="lower right", frameon=False, fontsize=7.6,
              handlelength=2.6, borderaxespad=0.6)
    fig.tight_layout()
    save(fig, "tier_geometry")

    print(f"  P* = {p_star}")
    for tier in TIERS:
        g, s = cfg["guess"][tier], cfg["slip"][tier]
        star = stars[tier]
        reached = f"{star:.3f}" if star is not None else "never (max < P*)"
        print(f"  {tier:<7} g={g:.2f} s={s:.2f} max={1 - s:.3f} theta*={reached}")


if __name__ == "__main__":
    main()
