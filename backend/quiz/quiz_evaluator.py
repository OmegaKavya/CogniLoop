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
                
            # 2. Batch AI Evaluation
            if eval_requests:
                prompt = "Evaluate the following student answers.\n\n"
                for req in eval_requests:
                    prompt += f"[ID: {req['id']}]\nQuestion: {req['question']}\nCorrect Answer: {req['correct_answer']}\nStudent's Answer: {req['selected']}\n\n"
                
                prompt += """
                For each ID, act as an expert tutor.
                1. Determine if the Student's Answer is semantically identical or correct regarding the Question.
                2. Provide a 1-sentence supportive explanation.
                
                Return ONLY a JSON array of objects with this structure (no markdown blocks, just raw JSON):
                [
                    {"id": "the_id", "is_correct": true/false, "feedback": "Your explanation here"}
                ]
                """
                
                batch_results = self.client.complete_json(
                    prompt,
                    system="You are an expert tutor grading answers. Return valid "
                           "JSON only, with no markdown and no explanation.",
                    max_tokens=1500,
                    temperature=0.2,
                    ollama_timeout=config.OLLAMA_EVAL_TIMEOUT,
                ) or []

                if isinstance(batch_results, dict):
                    # Models sometimes wrap the array, e.g. {"results": [...]}
                    batch_results = (batch_results.get('results')
                                     or batch_results.get('evaluations') or [])

                if isinstance(batch_results, list):
                    by_id = {r['id']: r for r in eval_requests}
                    for res in batch_results:
                        if not isinstance(res, dict):
                            continue
                        res_id = str(res.get('id'))
                        req = by_id.get(res_id)
                        if req:
                            results_map[res_id] = {
                                "question_id": res_id,
                                "is_correct": bool(res.get('is_correct', False)),
                                "time_taken": req['time_taken'],
                                "feedback": res.get('feedback', '')
                            }

            # 3. Deterministic fallback for anything the model did not grade
            for req in eval_requests:
                if req['id'] not in results_map:
                    graded = self._match_fallback(req['selected'], req['correct_answer'])
                    results_map[req['id']] = {
                        "question_id": req['id'],
                        "is_correct": graded["is_correct"],
                        "time_taken": req['time_taken'],
                        "feedback": graded["feedback"],
                    }

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
