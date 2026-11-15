import json
import random

from backend.llm import LLMClient, llm_client


class QuizGenerator:
    """Builds adaptive quizzes, falling back to a static pool without a model.

    Provider selection, gating and timeouts live in LLMClient so that generation
    and evaluation cannot drift apart in which providers they support.
    """

    def __init__(self, ollama_url=None, model=None, client=None):
        if client is not None:
            self.client = client
        elif ollama_url is not None or model is not None:
            self.client = LLMClient(ollama_url=ollama_url, ollama_model=model)
        else:
            self.client = llm_client

    def _get_transcript_text(self, youtube_id, watch_time=0):
        if not youtube_id:
            return None
        try:
            from backend.quiz.rag_retriever import rag_retriever
            query = "Core concepts, definitions, mechanisms, and examples"
            context = rag_retriever.get_context(youtube_id, query=query, top_k=5)
            return context if context else None
        except Exception as e:
            print(f"RAG service error: {e}")
            return None

    def _get_question_count(self, mastery, speed_label):
        speed = (speed_label or "Steady").lower()
        if speed == "slow":
            base_min, base_max = 9, 10
        elif speed == "fast":
            base_min, base_max = 7, 8
        else:
            base_min, base_max = 8, 10

        if mastery < 0.35:
            base_max = min(base_max + 1, 10)
        elif mastery > 0.75:
            base_min = max(base_min - 1, 6)

        return random.randint(base_min, base_max)

    def _get_adaptive_difficulty(self, difficulty, speed_label):
        """The difficulty tier to serve. This is the caller's tier, unchanged.

        This method used to override the caller with `random.choice` based on a
        speed label, which broke the adaptation loop in three places at once:
        the bandit selected one arm, a coin flip served a different tier, and
        the arm that was selected got credited with the outcome of the tier that
        was served. A policy cannot learn from an action log that does not record
        what it actually did.

        Difficulty now has exactly one owner - the bandit (or the fixed tier,
        for the control group). Response speed still adapts the quiz, but
        through `_get_question_count`, where it does not contend for the same
        decision.
        """
        return difficulty

    def _normalize_text(self, text):
        return " ".join(str(text or "").strip().lower().split())

    def _ensure_unique_questions(self, questions, num_questions, avoid_questions=None):
        avoid = {self._normalize_text(q) for q in (avoid_questions or []) if q}
        seen = set(avoid)
        unique = []

        if isinstance(questions, list):
            for question in questions:
                if not isinstance(question, dict):
                    continue
                text = question.get("text")
                norm = self._normalize_text(text)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                unique.append(question)
                if len(unique) >= num_questions:
                    break

        for idx, question in enumerate(unique, start=1):
            question["id"] = idx

        return unique

    def _build_prompt(self, topic_id, topic_name, num_questions, adaptive_difficulty,
                      cluster, speed_label, mastery, context_prompt, avoid_questions):
        if mastery < 0.4:
            mastery_instruction = "Focus on foundational concepts - the learner has low mastery."
        elif mastery > 0.7:
            mastery_instruction = "Include challenging analytical questions - the learner has high mastery."
        else:
            mastery_instruction = "Balance conceptual and applied questions."

        avoid_list = json.dumps((avoid_questions or [])[:15])

        return f"""{context_prompt}
Generate a {num_questions}-question MCQ quiz on: {topic_name}
Difficulty: {adaptive_difficulty}. Learner profile: {cluster}. Speed: {speed_label}.
{mastery_instruction}

Rules:
1. Questions MUST test {topic_name} concepts only - no study habits or generic advice.
2. Progression: first ~30% foundational, middle ~40% mechanisms/applications, last ~30% scenario/edge-cases.
3. Each question: one clearly correct answer + 3 plausible distractors.
4. Hints: guide reasoning without revealing the answer.
5. Avoid repeating: {avoid_list}

Return ONLY valid JSON:
{{"topic_id":"{topic_id}","difficulty":"{adaptive_difficulty}","num_questions":{num_questions},"questions":[{{"id":1,"text":"...","options":["A","B","C","D"],"answer":"exact correct option text","hint":"..."}}]}}"""

    def _is_valid_quiz(self, quiz_data, min_questions=5):
        if not quiz_data or not isinstance(quiz_data, dict):
            return False
        questions = quiz_data.get("questions")
        if not questions or not isinstance(questions, list):
            return False
        if len(questions) < min_questions:
            print(f"[QuizGen] Validation failed: got only {len(questions)} questions, expected at least {min_questions}")
            return False
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                print(f"[QuizGen] Validation failed at index {idx}: question is not a dictionary")
                return False
            text = q.get("text")
            options = q.get("options")
            answer = q.get("answer")
            if not text or not isinstance(text, str) or not text.strip():
                print(f"[QuizGen] Validation failed at index {idx}: missing or empty 'text'")
                return False
            if not options or not isinstance(options, list) or len(options) < 4:
                print(f"[QuizGen] Validation failed at index {idx}: 'options' must be a list with at least 4 items")
                return False
            if not all(isinstance(opt, str) and opt.strip() for opt in options):
                print(f"[QuizGen] Validation failed at index {idx}: 'options' contains empty or non-string elements")
                return False
            normalized_answer = self._normalize_text(answer)
            normalized_options = [self._normalize_text(opt) for opt in options]
            if not normalized_answer or normalized_answer not in normalized_options:
                print(f"[QuizGen] Validation failed at index {idx}: 'answer' ({answer}) must match one of the 'options'")
                return False
        return True

    def generate_quiz(self, topic_id, topic_name, youtube_id, watch_time=0,
                      difficulty="medium", mastery=0.3, cluster="General Learner",
                      speed_label="Steady", avoid_questions=None):

        num_questions = self._get_question_count(mastery, speed_label)
        adaptive_difficulty = self._get_adaptive_difficulty(difficulty, speed_label)
        print(f"[QuizGen] difficulty={adaptive_difficulty}, questions={num_questions}, mastery={mastery:.2f}, cluster={cluster}, speed={speed_label}")

        transcript_context = self._get_transcript_text(youtube_id, watch_time)
        if transcript_context and transcript_context != "No relevant context found in transcript.":
            context_prompt = f"Use this retrieved video transcript context:\n\n{transcript_context}\n"
        else:
            context_prompt = f"Topic: {topic_name}. Use general academic knowledge.\n"

        prompt = self._build_prompt(
            topic_id, topic_name, num_questions, adaptive_difficulty,
            cluster, speed_label, mastery, context_prompt, avoid_questions
        )

        quiz_data = self.client.complete_json(
            prompt,
            system="You are an expert educational quiz generator. Always return "
                   "valid JSON only, no markdown, no explanation.",
            max_tokens=2500,
            temperature=0.7,
        )
        if not quiz_data:
            print(f"[QuizGen] No model output from {self.client.providers() or 'any provider'}")

        # Static fallback
        if not quiz_data or "questions" not in quiz_data:
            print("[QuizGen] Using static fallback questions")
            return self._shuffle_question_options(
                self._get_fallback_quiz(topic_id, topic_name, adaptive_difficulty, num_questions, avoid_questions))

        cleaned_questions = self._ensure_unique_questions(
            quiz_data.get("questions", []),
            num_questions,
            avoid_questions=avoid_questions
        )

        quiz_data["questions"] = cleaned_questions
        quiz_data["num_questions"] = len(cleaned_questions)
        # The model echoes a `difficulty` field back, and what it echoes is not
        # reliably the tier it was asked for. The served tier is authoritative:
        # it is what the bandit chose and what its arm will be credited with.
        quiz_data["difficulty"] = adaptive_difficulty

        if not self._is_valid_quiz(quiz_data, min_questions=5):
            print("[QuizGen] Validation failed for LLM generated quiz. Falling back to static questions.")
            return self._shuffle_question_options(
                self._get_fallback_quiz(topic_id, topic_name, adaptive_difficulty, num_questions, avoid_questions))

        print(f"[QuizGen] Returning {len(cleaned_questions)} unique questions")
        return self._shuffle_question_options(quiz_data)

    @staticmethod
    def _shuffle_question_options(quiz_data):
        """Randomise option order within each question.

        Authored fallback questions list the correct answer first, and a model
        asked for JSON tends to do the same. Served in that order, a learner who
        notices can score full marks by always picking the first option. That
        matters more here than for the in-video checkpoints: quiz scores feed
        mastery estimation and the difficulty policy, so a positional shortcut
        would saturate mastery and corrupt the signal the system adapts on.

        The answer is stored as its exact text rather than an index, so
        reordering the options cannot invalidate it.
        """
        for question in (quiz_data or {}).get("questions", []):
            options = question.get("options")
            if isinstance(options, list) and len(options) > 1:
                random.shuffle(options)
        return quiz_data

    def _get_fallback_quiz(self, topic_id, topic_name, difficulty, num_questions=7, avoid_questions=None):
        try:
            from utils.constants import SUBMODULE_DEFINITIONS
            if topic_id in SUBMODULE_DEFINITIONS:
                all_questions = []
                for sub in SUBMODULE_DEFINITIONS[topic_id]:
                    for cp in sub.get("checkpoints", []):
                        correct_text = cp["options"][cp["correct_index"]]
                        all_questions.append({
                            "id": cp["id"],
                            "text": cp["question"],
                            "options": cp["options"],
                            "answer": correct_text,
                            "hint": cp["explanation"]
                        })
                if all_questions:
                    random.shuffle(all_questions)
                    unique_questions = self._ensure_unique_questions(all_questions, num_questions, avoid_questions=avoid_questions)
                    if not unique_questions:
                        unique_questions = all_questions[:num_questions]
                    for idx, question in enumerate(unique_questions, start=1):
                        question["id"] = idx
                    return {
                        "topic_id": topic_id,
                        "difficulty": difficulty,
                        "num_questions": len(unique_questions),
                        "questions": unique_questions
                    }
        except Exception as e:
            print(f"[QuizGen] Specific fallback failed, using generic: {e}")

        all_questions = [
            {"id": 1, "text": f"Which statement best defines the core purpose of {topic_name}?",
             "options": ["A framework for modeling and solving domain-specific problems", "A memorization-only method with no decision-making", "A topic used only for historical context", "A concept unrelated to system behavior"],
             "answer": "A framework for modeling and solving domain-specific problems", "hint": "Pick the option that captures what the topic is fundamentally used for."},
            {"id": 2, "text": f"In {topic_name}, why are foundational concepts introduced before advanced techniques?",
             "options": ["Advanced reasoning depends on core principles", "Because advanced concepts are less useful", "Only beginners need theory", "Order does not affect understanding"],
             "answer": "Advanced reasoning depends on core principles", "hint": "Look for the dependency relationship between basics and advanced ideas."},
            {"id": 3, "text": f"Which scenario is the best example of applying {topic_name} conceptually rather than mechanically?",
             "options": ["Choosing an approach based on constraints and explaining why", "Applying the same fixed steps to every problem", "Ignoring assumptions and focusing only on final output", "Selecting options by pattern matching alone"],
             "answer": "Choosing an approach based on constraints and explaining why", "hint": "Conceptual use means adapting ideas to context."},
            {"id": 4, "text": f"When comparing two methods in {topic_name}, which criterion most directly reflects conceptual correctness?",
             "options": ["How well assumptions match the problem model", "How quickly the answer was guessed", "How long the option text is", "How familiar the method name sounds"],
             "answer": "How well assumptions match the problem model", "hint": "Correctness starts with valid assumptions."},
            {"id": 5, "text": f"A common misconception in {topic_name} is that one rule fits all situations. Why is this incorrect?",
             "options": ["Different constraints require different conceptual choices", "Rules never work in any context", "Concepts are optional for real systems", "All problems in the topic are identical"],
             "answer": "Different constraints require different conceptual choices", "hint": "Think about variability in constraints and goals."},
            {"id": 6, "text": f"In {topic_name}, what is the most reliable way to evaluate whether a solution generalizes beyond one example?",
             "options": ["Test reasoning against edge cases and changed assumptions", "Check only one successful case", "Prefer the shortest explanation", "Reuse the previous answer unchanged"],
             "answer": "Test reasoning against edge cases and changed assumptions", "hint": "Generalization requires stress-testing the model, not one sample."},
            {"id": 7, "text": f"Which change would most likely break a valid solution approach in {topic_name}?",
             "options": ["Violating a core assumption of the approach", "Renaming variables consistently", "Reordering equivalent explanation steps", "Using clearer notation"],
             "answer": "Violating a core assumption of the approach", "hint": "Identify what the approach fundamentally depends on."},
            {"id": 8, "text": f"An advanced decision in {topic_name} usually involves which trade-off?",
             "options": ["Balancing optimality, complexity, and constraints", "Choosing whichever method is newest", "Maximizing steps regardless of outcomes", "Ignoring failure modes"],
             "answer": "Balancing optimality, complexity, and constraints", "hint": "Advanced decisions are rarely one-dimensional."},
            {"id": 9, "text": f"In a failure analysis for {topic_name}, what question best targets root cause?",
             "options": ["Which assumption or model condition was violated?", "Who answered fastest?", "Which explanation used more keywords?", "How many times was the solution repeated?"],
             "answer": "Which assumption or model condition was violated?", "hint": "Root cause analysis starts from model breakdowns."},
            {"id": 10, "text": f"Which option represents higher-order understanding in {topic_name}?",
             "options": ["Predicting behavior under unseen constraints", "Recalling one definition verbatim", "Selecting by elimination without reasoning", "Repeating a solved example exactly"],
             "answer": "Predicting behavior under unseen constraints", "hint": "Higher-order understanding supports prediction in new situations."},
        ]
        random.shuffle(all_questions)
        unique_questions = self._ensure_unique_questions(all_questions, num_questions, avoid_questions=avoid_questions)
        if not unique_questions:
            unique_questions = all_questions[:num_questions]
            for idx, question in enumerate(unique_questions, start=1):
                question["id"] = idx

        return {
            "topic_id": topic_id,
            "difficulty": difficulty,
            "num_questions": len(unique_questions),
            "questions": unique_questions
        }


quiz_gen = QuizGenerator()