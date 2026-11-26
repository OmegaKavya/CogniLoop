from backend.repositories.core_repositories import user_repo, quiz_repo

class AnalyticsEngine:
    """Normalized learning gain per arm, measured on the probe quizzes only."""
    
    def calculate_nlg(self, pre_test, post_test):
        """Calculates Normalized Learning Gain (NLG)"""
        if pre_test == 100:
            return 0 if post_test < 100 else 1.0 # Edge case
        return (post_test - pre_test) / (100 - pre_test)
        
    def generate_experiment_report(self):
        users = user_repo.get_all()
        if not isinstance(users, list):
            users = []
            
        report = {
            "control": {"nlg": [], "scores": [], "engagement": []},
            "experimental": {"nlg": [], "scores": [], "engagement": []}
        }
        
        # Read once and group, rather than once per registered user. The old
        # loop called get_user_attempts inside it, so the cost of this endpoint
        # was the whole attempts document times the number of accounts. Scores
        # are all it reads, so the per-question results are left behind too.
        by_user = {}
        for attempt in quiz_repo.all_attempts(include_responses=False):
            by_user.setdefault(str(attempt.get('user_id')), []).append(attempt)

        excluded = {"control": 0, "experimental": 0}

        for user in users:
            if not isinstance(user, dict) or user.get('deleted'):
                continue
            uid = user.get('id')
            group = user.get('study_group', 'experimental')
            if group not in report:
                continue

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
                pre = next((a for a in topic_attempts
                            if (a.get('quiz_meta') or {}).get('probe') == 'pre'), None)
                if pre is None:
                    continue
                after = topic_attempts[topic_attempts.index(pre) + 1:]
                posts = [a for a in after if (a.get('quiz_meta') or {}).get('probe') == 'post']
                if not posts:
                    continue
                if best is None or len(topic_attempts) > len(best[2]):
                    best = (pre, posts[-1], topic_attempts)

            if best is None:
                # Took part but never reached a check quiz: reported, so a
                # difference in drop-out between arms is visible rather than
                # silently filtered away.
                if by_user.get(str(uid)):
                    excluded[group] += 1
                continue

            pre, post, topic_attempts = best
            pre_test = pre.get('score', 0)
            post_test = post.get('score', 0)
            report[group]["nlg"].append(self.calculate_nlg(pre_test, post_test))
            report[group]["scores"].append(post_test)
            report[group]["engagement"].append(len(topic_attempts))

        # Calculate averages
        summary = {}
        for group in ["control", "experimental"]:
            nlg_list = report[group]["nlg"]
            avg_nlg = sum(nlg_list) / len(nlg_list) if nlg_list else 0
            
            eng_list = report[group]["engagement"]
            avg_eng = sum(eng_list) / len(eng_list) if eng_list else 0
            
            summary[group] = {
                "user_count": len(nlg_list),
                "without_check_quiz": excluded[group],
                "avg_nlg": round(avg_nlg, 3),
                "avg_engagement_quizzes": round(avg_eng, 1)
            }
            
        try:
            from scipy import stats
            if report['control']['nlg'] and report['experimental']['nlg']:
                t_stat, p_val = stats.ttest_ind(report['experimental']['nlg'], report['control']['nlg'])
                summary["statistical_significance"] = {
                    "p_value": round(float(p_val), 4),
                    "is_significant": bool(p_val < 0.05)
                }
        except ImportError:
            summary["statistical_significance"] = "scipy not installed. T-test skipped."
            
        return summary

analytics_engine = AnalyticsEngine()
