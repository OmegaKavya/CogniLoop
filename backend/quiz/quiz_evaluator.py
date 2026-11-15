from backend import config
from backend.llm import LLMClient, llm_client


class QuizEvaluator:
    """Grades submitted answers, using a language model where one is available.

    Grading must never depend on the model: an unreachable or misbehaving
    provider falls back to exact answer matching, which is deterministic and
    always correct for multiple-choice items. The model only adds semantic
    tolerance and per-question feedback.
    """

    def __init__(self, ollama_url=None, client=None):
        if client is not None:
            self.client = client
        elif ollama_url is not None:
            # Preserved for callers that point the evaluator at a specific host.
            self.client = LLMClient(ollama_url=ollama_url)
        else:
            self.client = llm_client

    @staticmethod
    def _match_fallback(selected, correct_answer):
        is_correct = str(selected).strip().lower() == str(correct_answer).strip().lower()
        return {
            "is_correct": is_correct,
            "feedback": "Great focus on the core concept!" if is_correct else "Review the key principles of this topic."
        }

    def evaluate(self, quiz, responses):
        try:
            if not quiz:
                return None

            correct_count = 0
            total_time = 0
            question_results = []
            
            # 1. Prepare evaluation requests
            eval_requests = []
            results_map = {}
            
            for resp in responses:
                q_id = str(resp['question_id'])
                selected = resp['selected_answer']
                time_taken = resp['time_taken']
                total_time += time_taken
                
                question_data = next((q for q in quiz['questions'] if str(q['id']) == q_id), None)
                if not question_data:
                    results_map[q_id] = {
                        "question_id": q_id,
                        "is_correct": False,
                        "time_taken": time_taken,
                        "feedback": "Question not found."
                    }
                    continue
                    
                correct_ans = question_data.get('answer') or question_data.get('correct_answer') or question_data.get('correct') or ""
                if not selected or str(selected).strip() == "" or str(selected).strip().lower() == "none":
                    results_map[q_id] = {
                        "question_id": q_id,
                        "is_correct": False,
                        "time_taken": time_taken,
                        "feedback": f"No answer was selected. The correct concept focuses on: {correct_ans}"
                    }
                    continue
                    
                eval_requests.append({
                    "id": q_id,
                    "question": question_data.get('text', ''),
                    "correct_answer": correct_ans,
                    "selected": selected,
                    "time_taken": time_taken
                })
                
            # 2. Grade deterministically. This is the authority, for every
            #    question, whether or not a model is reachable.
            #
            #    These are multiple-choice items and we hold the exact text of
            #    the correct option, so correctness is string equality. There is
            #    nothing here for a model to adjudicate, and letting one try
            #    means a single hallucinated `is_correct` silently flips the
            #    grade, the mastery update computed from it, and the difficulty
            #    the learner is routed to next.
            for req in eval_requests:
                graded = self._match_fallback(req['selected'], req['correct_answer'])
                req['is_correct'] = graded['is_correct']
                results_map[req['id']] = {
                    "question_id": req['id'],
                    "is_correct": graded["is_correct"],
                    "time_taken": req['time_taken'],
                    "feedback": graded["feedback"],
                }

            # 3. Ask the model for explanatory feedback only, and merge nothing
            #    else. It is told the verdict rather than asked for it, so its
            #    explanation always agrees with the grade the learner is shown.
            if eval_requests:
                prompt = "Write feedback for each graded answer below.\n\n"
                for req in eval_requests:
                    verdict = "CORRECT" if req['is_correct'] else "INCORRECT"
                    prompt += (f"[ID: {req['id']}]\nQuestion: {req['question']}\n"
                               f"Correct Answer: {req['correct_answer']}\n"
                               f"Student's Answer: {req['selected']}\n"
                               f"Verdict (already decided, do not dispute): {verdict}\n\n")

                prompt += """
                For each ID, act as an expert tutor and write a single
                supportive sentence explaining the concept behind the verdict.
                The verdict is final and is not yours to change.

                Return ONLY a JSON array of objects with this structure (no markdown blocks, just raw JSON):
                [
                    {"id": "the_id", "feedback": "Your explanation here"}
                ]
                """

                batch_results = self.client.complete_json(
                    prompt,
                    system="You are an expert tutor writing feedback on answers "
                           "that have already been graded. Return valid JSON "
                           "only, with no markdown and no explanation.",
                    max_tokens=1500,
                    temperature=0.2,
                    ollama_timeout=config.OLLAMA_EVAL_TIMEOUT,
                ) or []

                if isinstance(batch_results, dict):
                    # Models sometimes wrap the array, e.g. {"results": [...]}
                    batch_results = (batch_results.get('results')
                                     or batch_results.get('evaluations') or [])

                if isinstance(batch_results, list):
                    for res in batch_results:
                        if not isinstance(res, dict):
                            continue
                        res_id = str(res.get('id'))
                        entry = results_map.get(res_id)
                        feedback = res.get('feedback')
                        # Only the prose is taken. `is_correct` is ignored even
                        # when the model volunteers one.
                        if entry and isinstance(feedback, str) and feedback.strip():
                            entry["feedback"] = feedback.strip()

            # 4. Construct final results in order
            for resp in responses:
                q_id = str(resp['question_id'])
                res = results_map.get(q_id)
                if res:
                    question_results.append(res)
                    if res.get('is_correct'):
                        correct_count += 1

            q_count = len(quiz.get('questions', []))
            score = (correct_count / q_count) * 100 if q_count > 0 else 0
            avg_time = total_time / q_count if q_count > 0 else 0

            return {
                "score": round(score, 2),
                "avg_time": round(avg_time, 2),
                "total_time": round(total_time, 2),
                "question_results": question_results
            }
        except Exception as e:
            print(f"Evaluation error: {e}")
            import traceback
            traceback.print_exc()
            return None


evaluator = QuizEvaluator()
