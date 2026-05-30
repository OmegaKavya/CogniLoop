import json
import os
import requests
import random


class QuizGenerator:
    def __init__(self, ollama_url=None, model="llama3.2"):
        self.ollama_url = ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.ollama_model = model
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.groq_model = "llama-3.1-8b-instant"

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
        speed = (speed_label or "Steady").lower()
        if speed == "slow":
            if difficulty == "hard":
                return "medium"
            return random.choice(["easy", "medium"])
        if speed == "fast":
            if difficulty == "easy":
                return "medium"
            return random.choice(["medium", "hard"])
        return difficulty

    def _normalize_text(self, text):
        return " ".join(str(text or "").strip().lower().split())

    def _ensure_unique_questions(self, questions, num_questions, avoid_questions=None):
        avoid = {self._normalize_text(q) for q in (avoid_questions or []) if q}
        seen = set(avoid)
        unique = []

        for question in questions or []:
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
            mastery_instruction = "Focus on foundational concepts — the learner has low mastery."
        elif mastery > 0.7:
            mastery_instruction = "Include challenging analytical questions — the learner has high mastery."
        else:
            mastery_instruction = "Balance conceptual and applied questions."

        avoid_list = json.dumps((avoid_questions or [])[:15])

        return f"""{context_prompt}
Generate a {num_questions}-question MCQ quiz on: {topic_name}
Difficulty: {adaptive_difficulty}. Learner profile: {cluster}. Speed: {speed_label}.
{mastery_instruction}

Rules:
1. Questions MUST test {topic_name} concepts only — no study habits or generic advice.
2. Progression: first ~30% foundational, middle ~40% mechanisms/applications, last ~30% scenario/edge-cases.
3. Each question: one clearly correct answer + 3 plausible distractors.
4. Hints: guide reasoning without revealing the answer.
5. Avoid repeating: {avoid_list}

Return ONLY valid JSON:
{{"topic_id":"{topic_id}","difficulty":"{adaptive_difficulty}","num_questions":{num_questions},"questions":[{{"id":1,"text":"...","options":["A","B","C","D"],"answer":"exact correct option text","hint":"..."}}]}}"""

    def _try_groq(self, prompt, num_questions, topic_id, adaptive_difficulty, avoid_questions):
        """Use Groq API — ~30 RPM free, ~2s per quiz."""
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": "You are an expert educational quiz generator. Always return valid JSON only, no markdown, no explanation."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2500,
            "response_format": {"type": "json_object"}
        }
        response = requests.post(self.groq_url, headers=headers, json=payload, timeout=20)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        elif response.status_code == 429:
            print("[QuizGen] Groq rate limit hit, falling back to Ollama")
        else:
            print(f"[QuizGen] Groq error {response.status_code}: {response.text[:200]}")
        return None

    def _try_ollama(self, prompt):
        """Use local Ollama — unlimited but slow (~60-90s)."""
        response = requests.post(self.ollama_url, json={
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"num_predict": 2500, "temperature": 0.7}
        }, timeout=120)
        if response.status_code == 200:
            return json.loads(response.json().get("response", "{}"))
        return None

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

        quiz_data = None

        # Priority 1: Groq (fast, free cloud)
        if self.groq_api_key:
            try:
                print("[QuizGen] Trying Groq API...")
                quiz_data = self._try_groq(prompt, num_questions, topic_id, adaptive_difficulty, avoid_questions)
                if quiz_data:
                    print("[QuizGen] Groq succeeded")
            except requests.exceptions.Timeout:
                print("[QuizGen] Groq timeout, falling back to Ollama")
            except Exception as e:
                print(f"[QuizGen] Groq error: {e}")

        # Priority 2: Local Ollama (slow but offline)
        if not quiz_data:
            try:
                print("[QuizGen] Trying Ollama...")
                quiz_data = self._try_ollama(prompt)
                if quiz_data:
                    print("[QuizGen] Ollama succeeded")
            except requests.exceptions.ConnectionError:
                print("[QuizGen] Ollama not running")
            except requests.exceptions.Timeout:
                print("[QuizGen] Ollama timeout (>120s)")
            except Exception as e:
                print(f"[QuizGen] Ollama error: {e}")

        # Priority 3: Static fallback
        if not quiz_data or "questions" not in quiz_data:
            print("[QuizGen] Using static fallback questions")
            return self._get_fallback_quiz(topic_id, topic_name, adaptive_difficulty, num_questions, avoid_questions)

        cleaned_questions = self._ensure_unique_questions(
            quiz_data.get("questions", []),
            num_questions,
            avoid_questions=avoid_questions
        )

        if not cleaned_questions:
            return self._get_fallback_quiz(topic_id, topic_name, adaptive_difficulty, num_questions, avoid_questions)

        quiz_data["questions"] = cleaned_questions
        quiz_data["num_questions"] = len(cleaned_questions)
        print(f"[QuizGen] Returning {len(cleaned_questions)} unique questions")
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