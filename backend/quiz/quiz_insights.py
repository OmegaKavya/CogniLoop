import json
import re

from backend.llm import LLMClient, llm_client
from utils.constants import STATIC_CHEAT_SHEETS


class QuizInsightsEngine:
    """Produces post-quiz diagnostics, with a cheat-sheet fallback.

    Uses the shared LLM client so that insights, generation and grading agree on
    which providers exist; this module previously supported only Groq while
    grading supported only Ollama.
    """

    def __init__(self, ollama_url=None, model=None, client=None):
        if client is not None:
            self.client = client
        elif ollama_url is not None or model is not None:
            self.client = LLMClient(ollama_url=ollama_url, ollama_model=model)
        else:
            self.client = llm_client

    def _diagnose_question(self, q):
        """Return a time-based learning signal for each answer."""
        time_taken = q.get("time_taken", 0) or 0
        is_correct = q.get("is_correct", False)
        if is_correct:
            if time_taken < 2.5:
                return "lucky_guess"  # correct but suspiciously fast
            return None
        if time_taken < 5:
            return "guessed"       # answered too fast - likely random
        elif time_taken > 25:
            return "confused"      # took long and still wrong - genuine gap
        else:
            return "misconception" # moderate time - likely a specific misconception

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
            pace_advice = "Many answers were selected very quickly: slow down and read each option carefully before answering."
        elif confused / n > 0.5:
            pace_advice = "Several questions took a long time and were still wrong: these are genuine concept gaps that need targeted review."
        else:
            pace_advice = "Some answers reflect specific misconceptions: targeted re-reading of those concepts should help."

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
            {"title": f"{topic_name} - CogniLoop Study Notes", "url": f"/video/{topic_id}#study-notes"},
            {"title": f"{topic_name} - GeeksforGeeks", "url": f"https://www.geeksforgeeks.org/{topic_name.lower().replace(' ', '-')}/"},
            {"title": f"{topic_name} - GATE Practice Questions", "url": f"https://www.geeksforgeeks.org/gate-cs-notes-gq/?q={topic_name.replace(' ', '+')}"}
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
                "lucky_guess": 0,
                "pace_advice": pace_advice
            }
        }

    def _compute_diagnoses(self, question_results):
        """Compute time-based diagnoses across ALL questions (correct and incorrect)."""
        all_diagnoses = [self._diagnose_question(q) for q in question_results]
        incorrect_diagnoses = [d for d, q in zip(all_diagnoses, question_results) if not q.get("is_correct") and d]
        lucky_guesses = all_diagnoses.count("lucky_guess")
        guessed = incorrect_diagnoses.count("guessed")
        confused = incorrect_diagnoses.count("confused")
        misconception = incorrect_diagnoses.count("misconception")
        n = len(incorrect_diagnoses) or 1

        if guessed / n > 0.5:
            pace_advice = "Many wrong answers were selected very quickly: slow down and read each option carefully."
        elif confused / n > 0.5:
            pace_advice = "Several questions took a long time and were still wrong: these are genuine concept gaps."
        elif lucky_guesses >= 3:
            pace_advice = f"{lucky_guesses} correct answers came suspiciously fast (< 2.5s): make sure you're reading fully."
        else:
            pace_advice = "Some answers reflect specific misconceptions: targeted re-reading should help."

        return {
            "guessed": guessed,
            "confused": confused,
            "misconception": misconception,
            "lucky_guess": lucky_guesses,
            "pace_advice": pace_advice
        }

    def generate_insights(self, topic_name, score, mastery, question_results,
                          topic_id="", use_model=True):
        """Insights for an attempt.

        `use_model=False` returns the deterministic version without touching
        the network. The submit handler uses it so that a learner's result is
        not held behind a model call: scoring, mastery and the next difficulty
        are all computed locally and the model only ever rewrites the advice
        text. With three providers tried in turn at their own timeouts, a
        submission could otherwise wait minutes on a service that was down, for
        prose the learner has not scrolled to yet.

        The model version is produced afterwards, off the request, by
        `model_insights`, and written over this one.
        """
        incorrect = [q for q in question_results if not q.get("is_correct")]
        diagnoses = self._compute_diagnoses(question_results)

        if not incorrect:
            return {
                "focus_concepts": ["Advanced Application", "Speed + Accuracy", "Concept Transfer"],
                "cheat_sheet": [
                    "Attempt mixed-difficulty questions with a strict 10s timer.",
                    "Teach one concept aloud in 2 minutes from memory - no notes.",
                    "Solve one unseen problem and write your full reasoning.",
                    "Review the exam-angle notes in each submodule."
                ],
                "resources": [
                    {"title": f"Advanced {topic_name} - GATE PYQs", "url": f"https://www.geeksforgeeks.org/gate-cs-notes-gq/?q={topic_name.replace(' ', '+')}"},
                    {"title": f"{topic_name} interview questions", "url": f"https://www.geeksforgeeks.org/{topic_name.lower().replace(' ', '-')}-interview-questions/"}
                ],
                "summary": f"Perfect score! You have strong recall. Shift focus to application-level and transfer-based questions to cement mastery.",
                "diagnoses": diagnoses
            }

        if use_model:
            parsed = self._model_attempt(topic_name, score, mastery, incorrect)
            if parsed:
                parsed["diagnoses"] = diagnoses
                return parsed

        return self._smart_fallback(topic_id, topic_name, score, mastery, incorrect)

    def model_insights(self, topic_name, score, mastery, question_results):
        """The model-written version, or None if it is unavailable or failed.

        Separate from `generate_insights` so it can run after the response has
        gone out. Returns None rather than a fallback, because the caller
        already stored a fallback and should leave it alone unless there is
        something better to put there.
        """
        incorrect = [q for q in question_results if not q.get("is_correct")]
        if not incorrect:
            return None
        parsed = self._model_attempt(topic_name, score, mastery, incorrect)
        if not parsed:
            return None
        parsed["diagnoses"] = self._compute_diagnoses(question_results)
        return parsed

    def _model_attempt(self, topic_name, score, mastery, incorrect):
        """Ask the model to rewrite the advice. None on any failure."""
        if self.client.available:
            try:
                prompt = f"""You are an expert CS learning coach. A student scored {score}% on a {topic_name} quiz (mastery: {mastery:.0%}).
Wrong answers: {json.dumps([{"question": q.get("text",""), "chosen": q.get("selected_answer",""), "correct": q.get("correct_answer",""), "time_s": q.get("time_taken",0)} for q in incorrect])[:1800]}

Return ONLY JSON:
{{"focus_concepts":["concept 1","concept 2","concept 3"],"cheat_sheet":["action 1","action 2","action 3"],"resources":[{{"title":"...","url":"https://..."}}],"summary":"one diagnostic paragraph"}}"""

                parsed = self.client.complete_json(
                    prompt,
                    system="You are an expert CS learning coach. Return valid "
                           "JSON only, with no markdown and no explanation.",
                    max_tokens=600,
                    temperature=0.4,
                )
                if parsed and parsed.get("focus_concepts") and parsed.get("summary"):
                    return parsed
            except Exception as e:
                print(f"[Insights] model error: {e}")
        return None


insights_engine = QuizInsightsEngine()
