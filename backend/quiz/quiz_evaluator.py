import json
import requests

class QuizEvaluator:
    def __init__(self, ollama_url="http://localhost:11434/api/generate"):
        self.ollama_url = ollama_url
        self.model = "llama3.2"

    def _ai_verify_and_explain(self, question, selected, correct_answer):
        if not selected or str(selected).strip() == "" or str(selected).strip().lower() == "none":
            return {
                "is_correct": False,
                "feedback": f"No answer was selected. The correct concept focuses on: {correct_answer}"
            }

        prompt = f"""
        Question: {question}
        Student's Answer: {selected}
        Correct Answer: {correct_answer}
        
        Act as an expert tutor. 
        1. Determine if the Student's Answer is semantically identical or correct regarding the Question.
        2. Provide a 1-sentence supportive explanation of WHY it is correct or incorrect.
        
        Return the result ONLY as a JSON object with this structure:
        {{
            "is_correct": true/false,
            "feedback": "Your explanation here"
        }}
        """
        try:
            response = requests.post(self.ollama_url, json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }, timeout=15)
            
            if response.status_code == 200:
                return json.loads(response.json().get('response', '{}'))
        except Exception as e:
            print(f"AI Evaluation error: {e}")
        
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
                
                try:
                    response = requests.post(self.ollama_url, json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json"
                    }, timeout=30)
                    
                    if response.status_code == 200:
                        batch_results = json.loads(response.json().get('response', '[]'))
                        if isinstance(batch_results, dict):
                            # Sometimes LLMs return {"results": [...]}
                            batch_results = batch_results.get('results', [])
                        for res in batch_results:
                            res_id = str(res.get('id'))
                            # Match it back to original request
                            req = next((r for r in eval_requests if r['id'] == res_id), None)
                            if req:
                                results_map[res_id] = {
                                    "question_id": res_id,
                                    "is_correct": res.get('is_correct', False),
                                    "time_taken": req['time_taken'],
                                    "feedback": res.get('feedback', '')
                                }
                except Exception as e:
                    print(f"AI Batch Evaluation error: {e}")
                    
            # 3. Fallback for any failed AI evaluations
            for req in eval_requests:
                if req['id'] not in results_map:
                    is_correct = str(req['selected']).strip().lower() == str(req['correct_answer']).strip().lower()
                    results_map[req['id']] = {
                        "question_id": req['id'],
                        "is_correct": is_correct,
                        "time_taken": req['time_taken'],
                        "feedback": "Great focus on the core concept!" if is_correct else "Review the key principles of this topic."
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
