import math
from datetime import datetime

from backend.repositories.core_repositories import user_repo, quiz_repo

class AnalyticsEngine:
    """Normalized learning gain per arm, measured on the probe quizzes only."""
    
    def calculate_nlg(self, pre_test, post_test):
        """Normalised change from pre to post (Marx and Cummings, 2007).

        A gain is divided by the room there was to gain, (100 - pre), as in
        Hake's g; a loss by the room there was to lose, pre. Both halves lie
        in [-1, 1]. Hake's formula alone is unbounded below - 90 to 50 gives
        -4.0, so one participant who had a bad day on the check quiz would
        outweigh several who improved - and undefined at pre = 100.

        Returns None where change is undefined: no change at a ceiling or a
        floor (100 to 100, 0 to 0). Those participants are counted, not given
        an invented value.
        """
        if post_test == pre_test:
            return None if pre_test in (0, 100) else 0.0
        if post_test > pre_test:
            return (post_test - pre_test) / (100 - pre_test)
        return (post_test - pre_test) / pre_test

    def generate_experiment_report(self):
        users = user_repo.get_all()
        if not isinstance(users, list):
            users = []

        report = {
            "control": {"nlg": [], "scores": [], "engagement": [], "gap_hours": []},
            "experimental": {"nlg": [], "scores": [], "engagement": [], "gap_hours": []}
        }

        # Read once and group, rather than once per registered user. The old
        # loop called get_user_attempts inside it, so the cost of this endpoint
        # was the whole attempts document times the number of accounts. Scores
        # are all it reads, so the per-question results are left behind too.
        by_user = {}
        for attempt in quiz_repo.all_attempts(include_responses=False):
            by_user.setdefault(str(attempt.get('user_id')), []).append(attempt)

        excluded = {"control": 0, "experimental": 0}
        undefined = {"control": 0, "experimental": 0}

        for user in users:
            if not isinstance(user, dict) or user.get('deleted'):
                continue
            uid = user.get('id')

            # Measured on the probes only: the first quiz on a topic ("pre")
            # and the final check ("post"), which every learner in either arm
            # gets with identical generation inputs (app.PROBE_INPUTS).
            #
            # This used the first and last attempt on a topic. Practice
            # quizzes differ by arm - control is served medium, experimental
            # whatever the bandit picks - so the last practice score depended
            # on which tier happened to be served last, and the comparison
            # measured the routing as much as the learning. The project's
            # paper is about exactly that confound; the pilot must not have it.
            #
            # Pre and post are taken within one topic, never across topics.
            # Where a learner has both on several topics, the one with the most
            # attempts is used, since that is the one they actually worked at.
            by_topic = {}
            for attempt in by_user.get(str(uid), []):
                by_topic.setdefault(attempt.get('topic_id', 'unknown'), []).append(attempt)

            best = None
            for topic_attempts in by_topic.values():
                pre = next((a for a in topic_attempts if _probe(a) == 'pre'), None)
                if pre is None:
                    continue
                after = topic_attempts[topic_attempts.index(pre) + 1:]
                # The FIRST check quiz. The server issues only one per topic,
                # but attempts written before that rule existed may hold more,
                # and taking the last let a retake replace the outcome.
                post = next((a for a in after if _probe(a) == 'post'), None)
                if post is None:
                    continue
                if best is None or len(topic_attempts) > len(best[2]):
                    best = (pre, post, topic_attempts)

            # The arm the participant was in when they took the pre-test, as
            # recorded on the attempt. The user record says where they are
            # now, which differs if anyone is ever reassigned.
            first = (best[0] if best else
                     next(iter(by_user.get(str(uid), [])), None))
            group = ((first or {}).get('study_group')
                     or user.get('study_group', 'experimental'))
            if group not in report:
                continue

            if best is None:
                # Took part but never reached a check quiz: reported, so a
                # difference in drop-out between arms is visible rather than
                # silently filtered away.
                if by_user.get(str(uid)):
                    excluded[group] += 1
                continue

            pre, post, topic_attempts = best
            gain = self.calculate_nlg(pre.get('score', 0), post.get('score', 0))
            if gain is None:
                undefined[group] += 1
                continue
            report[group]["nlg"].append(gain)
            report[group]["scores"].append(post.get('score', 0))
            report[group]["engagement"].append(len(topic_attempts))
            report[group]["gap_hours"].append(_hours_between(pre, post))

        summary = {}
        for group in ["control", "experimental"]:
            nlg_list = report[group]["nlg"]
            eng_list = report[group]["engagement"]
            gaps = report[group]["gap_hours"]

            # The tester guide offers two tracks: one sitting, or three
            # sessions over about two weeks. Gains across a two-week gap and
            # within fifteen minutes are different quantities, so the report
            # splits them by the time actually elapsed between the two probes
            # rather than pooling them. An unknown gap counts as same day.
            same_day = [g for g, h in zip(nlg_list, gaps) if h is None or h < SAME_DAY_HOURS]
            later = [g for g, h in zip(nlg_list, gaps) if h is not None and h >= SAME_DAY_HOURS]

            summary[group] = {
                "user_count": len(nlg_list),
                "without_check_quiz": excluded[group],
                "gain_undefined": undefined[group],
                "avg_nlg": _mean(nlg_list),
                "same_day": {"user_count": len(same_day), "avg_nlg": _mean(same_day)},
                "across_sessions": {"user_count": len(later), "avg_nlg": _mean(later)},
                "avg_engagement_quizzes": round(sum(eng_list) / len(eng_list), 1) if eng_list else 0
            }

        summary["statistical_significance"] = _welch(
            report['experimental']['nlg'], report['control']['nlg'])
        return summary


SAME_DAY_HOURS = 12


def _probe(attempt):
    return (attempt.get('quiz_meta') or {}).get('probe')


def _hours_between(pre, post):
    try:
        start = datetime.fromisoformat(str(pre.get('timestamp')))
        end = datetime.fromisoformat(str(post.get('timestamp')))
    except (TypeError, ValueError):
        return None
    return (end - start).total_seconds() / 3600


def _mean(values):
    return round(sum(values) / len(values), 3) if values else 0


def _welch(a, b):
    """Welch's t-test, which does not assume the two arms vary equally.

    Returns a reason instead of a number when there is nothing to test. With
    one participant in an arm, or every gain identical, scipy returns NaN, and
    a NaN reached the analytics endpoint as a bare `NaN` token, which is not
    JSON: the page that reads it failed to parse the whole report.
    """
    if len(a) < 2 or len(b) < 2:
        return "Not enough participants: each arm needs at least two with both quizzes."
    try:
        from scipy import stats
    except ImportError:
        return "scipy not installed. T-test skipped."
    _, p_val = stats.ttest_ind(a, b, equal_var=False)
    if not math.isfinite(p_val):
        return "Not testable: every gain in at least one arm is identical."
    return {"test": "welch", "p_value": round(float(p_val), 4),
            "is_significant": bool(p_val < 0.05)}


analytics_engine = AnalyticsEngine()
