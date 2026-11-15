"""Shared visual language for the paper's figures.

Every figure in a paper should read as one system, so the palette, typography
and encoding rules live here rather than being restated in each script. A
figure that picks its own colours is how a paper ends up with three different
greens meaning three different things.

Palette
-------
A categorical palette validated against the page surface for colour-vision
deficiency and contrast. All checks pass: lightness band, chroma floor,
adjacent-pair CVD separation (worst pair dE 12.3 protan), normal-vision floor
(dE 24.6) and contrast against the surface.

Colour is never the only encoding. The figures are read in print and in
greyscale, so each tier also carries its own line style and marker, and series
are labelled directly or through a legend - never by hue alone.

The tier colours are semantic across the whole paper: teal always means the
easy tier, amber the medium, violet the hard. A figure comparing "too easy"
against "too hard" therefore uses teal and violet, so the reader does not have
to relearn the mapping.
"""

import os

import matplotlib

TIER_COLOR = {
    "easy":   "#0B8F84",
    "medium": "#D97706",
    "hard":   "#6D28D9",
}

TIER_STYLE = {
    "easy":   {"color": TIER_COLOR["easy"],   "ls": "--", "marker": "o"},
    "medium": {"color": TIER_COLOR["medium"], "ls": "-.", "marker": "s"},
    "hard":   {"color": TIER_COLOR["hard"],   "ls": ":",  "marker": "^"},
}

# Neutral ink for reference series, annotations and axes. A reference line is
# not a peer category, so it is never given a categorical hue.
INK = "#1c1917"
MUTED = "#57534e"
FAINT = "#78716c"
GRID = "#e7e5e4"

FIGURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paper", "figures")


def use_paper_style():
    """Apply the shared rcParams. Call before creating a figure."""
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 9,
        "axes.edgecolor": MUTED,
        "axes.linewidth": 0.8,
    })
    return plt


def despine(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        if side not in keep:
            ax.spines[side].set_visible(False)


def save(fig, stem):
    """Write <stem>.pdf for LaTeX and <stem>.png for quick inspection."""
    os.makedirs(FIGURE_DIR, exist_ok=True)
    out = os.path.join(FIGURE_DIR, f"{stem}.pdf")
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.replace(".pdf", ".png"), dpi=200, bbox_inches="tight")
    print(f"wrote {out}")
    return out
