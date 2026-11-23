from backend.repositories.core_repositories import user_repo, quiz_repo

class AnalyticsEngine:
    """Calculates Normalized Learning Gain and Statistical validities for the A/B testing."""
    
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

        for user in users:
            uid = user.get('id')
            group = user.get('study_group', 'experimental')

            # Pre/post within ONE topic, not across the whole history.
            #
            # This used the first and last attempt overall. With a single
            # curriculum that was merely imprecise; with Quantitative Aptitude
            # added alongside the computer science subjects it is wrong, because
            # a participant whose first attempt is Operating Systems and whose
            # last is percentages would have those two scores compared as if
            # they measured the same thing. The tester guide asks people not to
            # switch topics, but a metric should not depend on them complying.
            #
            # The topic with the most attempts is used, since that is the one
            # the participant actually worked at.
            attempts = by_user.get(str(uid), [])
            by_topic = {}
            for attempt in attempts:
                by_topic.setdefault(attempt.get('topic_id', 'unknown'), []).append(attempt)
            attempts = max(by_topic.values(), key=len) if by_topic else []

            if len(attempts) >= 2:
                pre_test = attempts[0].get('score', 0)
                post_test = attempts[-1].get('score', 0)
                nlg = self.calculate_nlg(pre_test, post_test)
                
                report[group]["nlg"].append(nlg)
                report[group]["scores"].append(post_test)
                report[group]["engagement"].append(len(attempts))
                
        # Calculate averages
        summary = {}
        for group in ["control", "experimental"]:
            nlg_list = report[group]["nlg"]
            avg_nlg = sum(nlg_list) / len(nlg_list) if nlg_list else 0
            
            eng_list = report[group]["engagement"]
            avg_eng = sum(eng_list) / len(eng_list) if eng_list else 0
            
            summary[group] = {
                "user_count": len(nlg_list),
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
