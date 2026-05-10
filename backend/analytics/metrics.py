import json
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
        
        for user in users:
            uid = user.get('id')
            group = user.get('study_group', 'experimental')
            
            # Simulated Pre/Post data fetch
            # In a full implementation, these would be dedicated DB fields.
            # Here we look at their first and last attempt overall
            attempts = quiz_repo.get_user_attempts(uid)
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
