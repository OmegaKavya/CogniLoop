"""Classification of a learner's response speed.

Scope
-----
This module owns one thing: turning an average response time into a label.

It used to also adjust difficulty - raising the tier for a fast high scorer and
lowering it for a slow low scorer. That has been removed rather than wired in,
because difficulty has a single owner: the contextual bandit. Two policies
adjusting the same variable is how the adaptation loop broke before, with the
tier the bandit selected, the tier actually served and the tier credited with
the outcome all able to differ.

Speed still adapts what the learner sees, through quiz length rather than
difficulty, which is a decision it does not contend for.

The thresholds were previously written out three times - here, inline in the
submit handler, and again as question timings - so a change in one place left
the others disagreeing. This class is now the only definition.
"""

from backend import config


class SpeedAdaptation:
    def __init__(self, fast_threshold=None, slow_threshold=None):
        self.fast_threshold = (config.SPEED_FAST_SECONDS
                               if fast_threshold is None else fast_threshold)
        self.slow_threshold = (config.SPEED_SLOW_SECONDS
                               if slow_threshold is None else slow_threshold)

    def speed_label(self, avg_time):
        """"Fast", "Slow" or "Steady" for an average seconds-per-question."""
        if avg_time < self.fast_threshold:
            return "Fast"
        if avg_time > self.slow_threshold:
            return "Slow"
        return "Steady"

    # Retained name for existing callers and tests.
    _get_speed_label = speed_label


speed_adapter = SpeedAdaptation()
