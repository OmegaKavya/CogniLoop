import json
import re
import requests
from utils.constants import STATIC_CHEAT_SHEETS


class QuizInsightsEngine:
    def __init__(self, ollama_url=None, model="llama3.2"):
        import os
        self.ollama_url = ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = model
        self.groq_model = "llama-3.1-8b-instant"

    def _diagnose_question(self, q):
        """Return a time-based learning signal for each wrong answer."""
        time_taken = q.get("time_taken", 0) or 0
        is_correct = q.get("is_correct", False)
        if is_correct:
            return None
        if time_taken < 5:
            return "guessed"       # answered too fast — likely random
        elif time_taken > 25:
            return "confused"      # took long and still wrong — genuine gap
        else:
            return "misconception" # moderate time — likely a specific misconception

    def _concept_from_cheat_sheet(self, topic_id, question_text):
        """Map a wrong question to the closest concept bullet in the cheat sheet."""
        sheet = STATIC_CHEAT_SHEETS.get(topic_id, {})
        core = sheet.get("core", [])
        pitfalls = sheet.get("pitfalls", [])
        q_lower = question_text.lower()
        for item in core + pitfalls:
            words = re.findall(r"[a-z]{4,}", item.lower())
            if any(w in q_lower for w in words[:6]):
                return item
        return None

    def _smart_fallback(self, topic_id, topic_name, score, mastery, incorrect_questions):
        """Diagnostic fallback that uses the cheat sheet for concept mapping."""
        sheet = STATIC_CHEAT_SHEETS.get(topic_id, {})
        pitfalls = sheet.get("pitfalls", [])
        drills = sheet.get("drills", [])
        core = sheet.get("core", [])

        # Map wrong questions to cheat-sheet concepts
        focus_concepts = []
        for q in incorrect_questions[:3]:
            concept = self._concept_from_cheat_sheet(topic_id, q.get("text", ""))
            if concept and concept not in focus_concepts:
                focus_concepts.append(concept)

        if not focus_concepts:
            # Extract keywords from wrong question text
            joined = " ".join(q.get("text", "") for q in incorrect_questions)
            tokens = re.findall(r"[A-Za-z]{5,}", joined)
            stop = {"which", "state", "about", "their", "there", "these", "those",
                    "option", "question", "correct", "answer", "following", "primary", "topic"}
            seen, kws = set(), []
            for t in tokens:
                tl = t.lower()
                if tl not in stop and tl not in seen:
                    seen.add(tl); kws.append(t.title())
                if len(kws) >= 3: break
            focus_concepts = kws or [topic_name, "core concepts"]

        # Time-based diagnosis
        diagnoses = [self._diagnose_question(q) for q in incorrect_questions]
        guessed  = diagnoses.count("guessed")
        confused = diagnoses.count("confused")
        n = len(incorrect_questions) or 1

        if guessed / n > 0.5:
            pace_advice = "Many answers were selected very quickly — slow down and read each option carefully before answering."
        elif confused / n > 0.5:
            pace_advice = "Several questions took a long time and were still wrong — these are genuine concept gaps that need targeted review."
        else:
            pace_advice = "Some answers reflect specific misconceptions — targeted re-reading of those concepts should help."

        # Build action plan from pitfalls + drills
        cheat_sheet = []
        if pitfalls:
            cheat_sheet.append(f"Watch out: {pitfalls[0]}")
        if drills:
            cheat_sheet.append(f"Drill: {drills[0]}")
        if len(drills) > 1:
            cheat_sheet.append(f"Drill: {drills[1]}")
        if not cheat_sheet:
            cheat_sheet = [
                "Re-read the core definition of each wrong concept in one sentence.",
                "Write one example for each concept you missed.",
                "Attempt 3 similar questions before retaking the quiz."
            ]

        resources = [
            {"title": f"{topic_name} — CogniLoop Study Notes", "url": f"https://nptel.ac.in/search?query={topic_name.replace(' ', '+')}"},
            {"title": f"{topic_name} — GeeksforGeeks", "url": f"https://www.geeksforgeeks.org/{topic_name.lower().replace(' ', '-')}/"},
            {"title": f"{topic_name} — GATE Practice Questions", "url": f"https://www.geeksforgeeks.org/gate-cs-notes-gq/?q={topic_name.replace(' ', '+')}"}
        ]

        if score >= 80:
            summary = f"Strong performance ({score}%). {pace_advice} Focus on the {len(incorrect_questions)} question(s) you missed to push toward mastery."
        elif score >= 50:
            summary = f"Moderate performance ({score}%). {pace_advice} The concepts listed below need targeted review before retaking."
        else:
            summary = f"Low score ({score}%). {pace_advice} Revisit the video modules covering these concepts before attempting another quiz."

        return {
            "focus_concepts": focus_concepts[:3],
            "cheat_sheet": cheat_sheet[:4],
            "resources": resources,
            "summary": summary,
            "diagnoses": {
                "guessed": guessed,
                "confused": confused,
                "misconception": diagnoses.count("misconception"),
                "pace_advice": pace_advice
            }
        }

    def generate_insights(self, topic_name, score, mastery, question_results, topic_id=""):
        incorrect = [q for q in question_results if not q.get("is_correct")]

        if not incorrect:
            return {
                "focus_concepts": ["Advanced Application", "Speed + Accuracy", "Concept Transfer"],
                "cheat_sheet": [
                    "Attempt mixed-difficulty questions with a strict 10s timer.",
                    "Teach one concept aloud in 2 minutes from memory — no notes.",
                    "Solve one unseen problem and write your full reasoning.",
                    "Review the exam-angle notes in each submodule."
                ],
                "resources": [
                    {"title": f"Advanced {topic_name} — GATE PYQs", "url": f"https://www.geeksforgeeks.org/gate-cs-notes-gq/?q={topic_name.replace(' ', '+')}"},
                    {"title": f"{topic_name} interview questions", "url": f"https://www.geeksforgeeks.org/{topic_name.lower().replace(' ', '-')}-interview-questions/"}
                ],
                "summary": f"Perfect score! You have strong recall. Shift focus to application-level and transfer-based questions to cement mastery.",
                "diagnoses": {"guessed": 0, "confused": 0, "misconception": 0, "pace_advice": "Excellent pace — keep it consistent."}
            }

        # Try Groq first (fast), then fallback
        if self.groq_api_key:
            try:
                prompt = f"""You are an expert CS learning coach. A student scored {score}% on a {topic_name} quiz (mastery: {mastery:.0%}).
Wrong answers: {json.dumps([{"question": q.get("text",""), "chosen": q.get("selected_answer",""), "correct": q.get("correct_answer",""), "time_s": q.get("time_taken",0)} for q in incorrect])[:1800]}

Return ONLY JSON:
{{"focus_concepts":["concept 1","concept 2","concept 3"],"cheat_sheet":["action 1","action 2","action 3"],"resources":[{{"title":"...","url":"https://..."}}],"summary":"one diagnostic paragraph"}}"""

                headers = {"Authorization": f"Bearer {self.groq_api_key}", "Content-Type": "application/json"}
                resp = requests.post(self.groq_url, headers=headers, json={
                    "model": self.groq_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 600,
                    "response_format": {"type": "json_object"}
                }, timeout=12)
                if resp.status_code == 200:
                    parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
                    if parsed.get("focus_concepts") and parsed.get("summary"):
                        parsed["diagnoses"] = {"guessed": 0, "confused": 0, "misconception": 0, "pace_advice": ""}
                        return parsed
            except Exception as e:
                print(f"[Insights] Groq error: {e}")

        return self._smart_fallback(topic_id, topic_name, score, mastery, incorrect)


insights_engine = QuizInsightsEngine()
