"""How to read a mastery estimate.

A percentage on its own tells a learner nothing: they cannot know whether 24%
is normal, alarming, or close to ready. The dashboard, the progress page and
the review page all showed bare numbers.

The bands below are presentation, not measurement - they describe where an
estimate sits, and say so. The estimate itself comes from the knowledge-tracing
model and is unchanged by anything here.

The 85% figure is not arbitrary: it is the success rate the difficulty policy
targets, following the interior-optimum result that learning is fastest when
roughly fifteen percent of items are still being missed.
"""

from backend import config

# (floor, label, meaning)
BANDS = (
    (0.85, "Exam ready", "At this level you are answering about as well as the policy aims for."),
    (0.70, "Solid",      "Most of this topic is holding. Keep going to push it to exam level."),
    (0.45, "Developing", "The basics are landing; the harder items are not reliable yet."),
    (0.00, "Early",      "Normal for a topic you have just started. It moves quickly at first."),
)

PRIOR = config.BKT_DEFAULTS["prior"]


def band(mastery):
    """Label and meaning for a mastery estimate in [0, 1]."""
    if mastery is None:
        return {"label": "Not started", "meaning": "Take a quiz to begin estimating this topic."}
    value = max(0.0, min(1.0, float(mastery)))
    for floor, label, meaning in BANDS:
        if value >= floor:
            return {"label": label, "meaning": meaning}
    return {"label": "Early", "meaning": BANDS[-1][2]}


def describe(mastery):
    """Band plus the percentage, for templates."""
    info = band(mastery)
    info["percent"] = None if mastery is None else round(float(mastery) * 100, 1)
    info["started"] = mastery is not None
    return info


def scale_note():
    """One sentence explaining the scale, for use beside a figure."""
    return (f"Estimated from your answers, not a raw score. "
            f"Everyone starts near {round(PRIOR * 100)}%; the difficulty policy "
            f"aims to keep you answering about 85% correctly.")
