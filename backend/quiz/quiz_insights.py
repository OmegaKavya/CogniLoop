import json
import re
from backend import config

from backend.llm import LLMClient, llm_client
from utils.constants import STATIC_CHEAT_SHEETS


def safe_link(url):
    """`url` if it is an https link or a path on this site, else None.

    Resource links come from a model, and a model can be steered by the
    answers it is shown. `javascript:` or `data:` in an href runs in the
    learner's session when clicked, and the page's policy allows inline
    script. A protocol-relative `//host` is refused too: it leaves the site
    while looking like a path.
    """
    if not isinstance(url, str):
        return None
    url = url.strip()
    if url.lower().startswith("https://") and len(url) > len("https://"):
        return url
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return None


def _practice_links(topic_id, topic_name, advanced=False):
    """Outside practice for a topic.

    Aptitude gets aptitude practice. It used to get the same GATE computer
    science links as every other topic, so a participant who chose it because
    they have no computer science background was sent to GATE CS notes.
    """
    if topic_id == "qa":
        return [
            {"title": "Aptitude questions and answers - GeeksforGeeks",
             "url": "https://www.geeksforgeeks.org/aptitude/aptitude-questions-and-answers/"},
            {"title": "Aptitude practice by topic - IndiaBix",
             "url": "https://www.indiabix.com/aptitude/questions-and-answers/"},
        ]
    slug = topic_name.lower().replace(' ', '-')
    query = topic_name.replace(' ', '+')
    if advanced:
        return [
            {"title": f"Advanced {topic_name} - GATE PYQs",
             "url": f"https://www.geeksforgeeks.org/gate-cs-notes-gq/?q={query}"},
            {"title": f"{topic_name} interview questions",
             "url": f"https://www.geeksforgeeks.org/{slug}-interview-questions/"},
        ]
    return [
        {"title": f"{topic_name} - GeeksforGeeks",
         "url": f"https://www.geeksforgeeks.org/{slug}/"},
        {"title": f"{topic_name} - GATE Practice Questions",
         "url": f"https://www.geeksforgeeks.org/gate-cs-notes-gq/?q={query}"},
    ]


def _clean_model_insights(parsed):
    """The model's JSON reduced to the shape the pages render, or None.

    Strings stay strings (the templates escape them), lists of strings stay
    lists of strings, and a resource survives only with a safe link.
    """
    if not isinstance(parsed, dict):
        return None

    def strings(value, limit):
        if not isinstance(value, list):
            return []
        return [v.strip() for v in value if isinstance(v, str) and v.strip()][:limit]

    summary = parsed.get("summary")
    focus = strings(parsed.get("focus_concepts"), 3)
    if not isinstance(summary, str) or not summary.strip() or not focus:
        return None

    resources = []
    for item in parsed.get("resources") or []:
        if not isinstance(item, dict):
            continue
        link, title = safe_link(item.get("url")), item.get("title")
        if link and isinstance(title, str) and title.strip():
            resources.append({"title": title.strip(), "url": link})

    return {
        "focus_concepts": focus,
        "cheat_sheet": strings(parsed.get("cheat_sheet"), 4),
        "resources": resources[:4],
        "summary": summary.strip(),
    }


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

    @staticmethod
    def _limit(time_limit):
        """The per-question budget in seconds, falling back to the default."""
        try:
            limit = float(time_limit or config.DEFAULT_QUESTION_SECONDS)
        except (TypeError, ValueError):
            limit = float(config.DEFAULT_QUESTION_SECONDS)
        if limit != limit or limit <= 0 or limit == float("inf"):
            limit = float(config.DEFAULT_QUESTION_SECONDS)
        return limit

    def diagnose_question(self, q, time_limit=None):
        """Public alias, used by the review page so it labels each question
        with the same thresholds the insights were computed with."""
        return self._diagnose_question(q, time_limit)

    def _diagnose_question(self, q, time_limit=None):
        """Return a time-based learning signal for one answer.

        Thresholds are fractions of the question's own time limit, not fixed
        seconds. With fixed seconds the "confused" branch required more than 25
        seconds on a question the client cuts off at 10 to 15, so it never once
        fired; every wrong answer slower than five seconds became a
        misconception. Fractions also make a diagnosis mean the same thing on
        an easy question and a hard one, which differ by 50% in budget.

        "Confused" now means the learner spent most of the time available and
        still got it wrong, which is the signal that was intended.
        """
        limit = self._limit(time_limit)

        time_taken = q.get("time_taken", 0) or 0
        try:
            time_taken = float(time_taken)
        except (TypeError, ValueError):
            time_taken = 0.0

        is_correct = q.get("is_correct", False)
        if is_correct:
            if time_taken < config.DIAGNOSIS_LUCKY_GUESS_FRACTION * limit:
                return "lucky_guess"  # correct but suspiciously fast
            return None
        if time_taken < config.DIAGNOSIS_GUESSED_FRACTION * limit:
            return "guessed"       # answered too fast - likely random
        elif time_taken >= config.DIAGNOSIS_CONFUSED_FRACTION * limit:
            return "confused"      # used the time and still wrong - genuine gap
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

    def _smart_fallback(self, topic_id, topic_name, score, mastery, incorrect_questions,
                        diagnoses):
        """Diagnostic fallback that uses the cheat sheet for concept mapping.

        `diagnoses` is the dict `_compute_diagnoses` already produced for this
        attempt. It is reused rather than recomputed: recomputing here dropped
        the quiz's time limit, so easy and hard quizzes were judged against the
        12-second default, and lucky guesses were reported as zero.
        """
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

        pace_advice = diagnoses["pace_advice"]

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
        ] + _practice_links(topic_id, topic_name)

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
            "diagnoses": diagnoses
        }

    def _compute_diagnoses(self, question_results, time_limit=None):
        """Compute time-based diagnoses across ALL questions (correct and incorrect)."""
        all_diagnoses = [self._diagnose_question(q, time_limit) for q in question_results]
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
            pace_advice = (f"{lucky_guesses} correct answers came suspiciously fast "
                           f"(under {config.DIAGNOSIS_LUCKY_GUESS_FRACTION * self._limit(time_limit):.0f}s): "
                           "make sure you're reading fully.")
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
                          topic_id="", use_model=True, time_limit=None):
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
        diagnoses = self._compute_diagnoses(question_results, time_limit)

        if not incorrect:
            return {
                "focus_concepts": ["Advanced Application", "Speed + Accuracy", "Concept Transfer"],
                "cheat_sheet": [
                    "Attempt mixed-difficulty questions with a strict 10s timer.",
                    "Teach one concept aloud in 2 minutes from memory - no notes.",
                    "Solve one unseen problem and write your full reasoning.",
                    "Review the exam-angle notes in each submodule."
                ],
                "resources": _practice_links(topic_id, topic_name, advanced=True),
                "summary": f"Perfect score! You have strong recall. Shift focus to application-level and transfer-based questions to cement mastery.",
                "diagnoses": diagnoses
            }

        if use_model:
            parsed = self._model_attempt(topic_name, score, mastery, incorrect)
            if parsed:
                parsed["diagnoses"] = diagnoses
                parsed["source"] = "model"
                return parsed

        return self._smart_fallback(topic_id, topic_name, score, mastery, incorrect,
                                    diagnoses)

    def model_insights(self, topic_name, score, mastery, question_results,
                       time_limit=None):
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
        parsed["diagnoses"] = self._compute_diagnoses(question_results, time_limit)
        # Marks the stored attempt as carrying the model's version, which is
        # how the results screen knows the rewrite has arrived.
        parsed["source"] = "model"
        return parsed

    def _model_attempt(self, topic_name, score, mastery, incorrect):
        """Ask the model to rewrite the advice. None on any failure."""
        if self.client.available:
            try:
                # The subject, not "CS". The curriculum now includes
                # Quantitative Aptitude, and telling the model it is a computer
                # science coach while handing it a percentages question biases
                # the advice toward a framing the question does not have.
                prompt = f"""You are an expert {topic_name} learning coach. A student scored {score}% on a {topic_name} quiz (mastery: {mastery:.0%}).
Wrong answers: {json.dumps([{"question": q.get("text",""), "chosen": q.get("selected_answer",""), "correct": q.get("correct_answer",""), "time_s": q.get("time_taken",0)} for q in incorrect])[:1800]}

Return ONLY JSON:
{{"focus_concepts":["concept 1","concept 2","concept 3"],"cheat_sheet":["action 1","action 2","action 3"],"resources":[{{"title":"...","url":"https://..."}}],"summary":"one diagnostic paragraph"}}"""

                parsed = self.client.complete_json(
                    prompt,
                    system=f"You are an expert {topic_name} learning coach. "
                           "Return valid JSON only, with no markdown and no "
                           "explanation.",
                    max_tokens=600,
                    temperature=0.4,
                )
                cleaned = _clean_model_insights(parsed)
                if cleaned:
                    return cleaned
            except Exception as e:
                print(f"[Insights] model error: {e}")
        return None


insights_engine = QuizInsightsEngine()
