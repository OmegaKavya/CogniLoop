from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import random
import secrets
import threading
from datetime import datetime, timedelta
import uuid
from utils.constants import STATIC_CHEAT_SHEETS
from backend import config
from backend.auth.auth_service import hash_password, verify_password
from backend.quiz.quiz_session import active_quiz_store, public_view
from backend.adaptation.speed_adaptation import speed_adapter
from backend import curriculum_stats
from backend import mastery_scale

app = Flask(__name__,
            template_folder='frontend/templates',
            static_folder='static')
_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    if os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError('SECRET_KEY environment variable must be set in production.')
    _secret_key = secrets.token_hex(32)
app.secret_key = _secret_key

# Session cookie hardening.
#
# SameSite=Lax stops the session cookie from being attached to cross-site POST
# requests, which is what a cross-site request forgery against these endpoints
# would rely on. Secure is required in production so the cookie is never sent
# over plain HTTP, but must stay off for local development, which is served
# over HTTP and would otherwise drop the cookie entirely.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=config.SESSION_LIFETIME_SECONDS),
)

from backend.ratelimit import SlidingWindowLimiter
from backend.repositories.core_repositories import (
    user_repo, progress_repo, quiz_repo, video_repo, QuizAttemptRepository)

login_limiter = SlidingWindowLimiter(
    config.LOGIN_MAX_ATTEMPTS, config.LOGIN_ATTEMPT_WINDOW_SECONDS)
register_limiter = SlidingWindowLimiter(
    config.REGISTER_MAX_ATTEMPTS, config.REGISTER_ATTEMPT_WINDOW_SECONDS)


def _client_address():
    """Best-effort client address for abuse limiting.

    Behind a proxy the peer address is the proxy, so the forwarded header is
    consulted. That header is attacker-controlled and is therefore used only to
    spread rate-limit buckets, never for authorisation.
    """
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'

# Remove load_json and save_json globally



def build_review_rows(attempts, topic_map):
    rows = []
    for attempt in sorted(attempts, key=lambda x: x.get('timestamp', ''), reverse=True):
        rows.append({
            "attempt_id": attempt.get("attempt_id", ""),
            "topic_id": attempt.get("topic_id"),
            "topic_name": topic_map.get(attempt.get("topic_id"), attempt.get("topic_id", "Topic")),
            "score": attempt.get("score", 0),
            "mastery": attempt.get("mastery", 0),
            "speed_label": attempt.get("adaptation", {}).get("speed_label", "Steady"),
            "timestamp": attempt.get("timestamp", ""),
            "insight_summary": attempt.get("ai_insights", {}).get("summary", "No AI insight available yet.")
        })
    return rows


def build_topic_heatmap_rows(attempts, topic_map):
    rows = []
    for topic_id, topic_name in topic_map.items():
        topic_attempts = [a for a in attempts if a.get('topic_id') == topic_id]
        if topic_attempts:
            count = len(topic_attempts)
            avg_score = round(sum(a.get('score', 0) for a in topic_attempts) / count, 1)
            avg_mastery = round((sum(a.get('mastery', 0) for a in topic_attempts) / count) * 100, 1)
            avg_time = round(sum(a.get('avg_time', 0) for a in topic_attempts) / count, 1)
            speed_values = [a.get('adaptation', {}).get('speed_label', 'Steady') for a in topic_attempts]
            fast_count = len([s for s in speed_values if s == 'Fast'])
            steady_count = len([s for s in speed_values if s == 'Steady'])
            slow_count = len([s for s in speed_values if s == 'Slow'])
            dominant_speed = 'Fast' if fast_count >= steady_count and fast_count >= slow_count else 'Slow' if slow_count >= steady_count else 'Steady'
        else:
            count = 0
            avg_score = 0
            avg_mastery = 0
            avg_time = 0
            dominant_speed = 'N/A'

        rows.append({
            'topic_id': topic_id,
            'topic_name': topic_name,
            'attempts': count,
            'score_value': avg_score,
            'mastery_value': avg_mastery,
            'speed_value': 95 if dominant_speed == 'Fast' else 70 if dominant_speed == 'Steady' else 45 if dominant_speed == 'Slow' else 0,
            'avg_time_value': max(0, min(100, int(100 - min(avg_time, 40) * 2.5))) if count else 0,
            'avg_score': avg_score,
            'avg_mastery': avg_mastery,
            'avg_time': avg_time,
            'dominant_speed': dominant_speed
        })
    return rows





def get_static_cheat_sheet(topic_id, topic_name):
    if topic_id in STATIC_CHEAT_SHEETS:
        return STATIC_CHEAT_SHEETS[topic_id]
    return {
        'title': f'{topic_name} Rapid Revision',
        'estimated_minutes': 4,
        'core': [
            f'Review core definitions and terminology of {topic_name}.',
            'Recall key process/flow from memory once.',
            'Revisit one example and one edge case.',
            'Summarize the most important comparison/trade-off.'
        ],
        'pitfalls': [
            'Mixing similarly named concepts.',
            'Skipping assumptions before solving.',
            'Answering from memory without checking context.'
        ],
        'drills': [
            'Explain one core concept in 2 lines.',
            'Write one common mistake and correction.',
            'Solve one quick practice prompt mentally.'
        ]
    }


def shuffle_checkpoint_options(checkpoints):
    """Randomise option order, keeping correct_index pointing at the right one.

    Every authored checkpoint lists its correct answer first. Presented in that
    order, "always pick the first option" scores full marks, so the checkpoint
    stops being a retrieval exercise and becomes a clicking exercise. Shuffling
    per request removes that shortcut.

    The checkpoints are formative: the result is shown to the learner and is not
    posted back, so it does not influence mastery estimation. The answer is
    therefore allowed to travel to the client, and only the ordering needs to
    vary.
    """
    shuffled = []
    for checkpoint in checkpoints:
        options = list(checkpoint.get('options') or [])
        index = checkpoint.get('correct_index', 0)
        if len(options) > 1 and 0 <= index < len(options):
            answer = options[index]
            random.shuffle(options)
            checkpoint = dict(checkpoint, options=options,
                              correct_index=options.index(answer))
        shuffled.append(checkpoint)
    return shuffled


def build_topic_submodules(video):
    from utils.constants import SUBMODULE_DEFINITIONS
    topic_id = video.get('id', '')
    video_id = video.get('video_id')

    # Use curated topic-specific submodules if available
    if topic_id in SUBMODULE_DEFINITIONS:
        submodules = []
        for idx, defn in enumerate(SUBMODULE_DEFINITIONS[topic_id]):
            submodules.append({
                "id": f"{topic_id}-m{idx+1}",
                "title": defn["title"],
                "objective": defn["objective"],
                "exam_angle": defn.get("exam_angle", ""),
                "video_id": defn.get("video_id") or video_id,
                "start_sec": defn["start_sec"],
                "end_sec": defn["end_sec"],
                "checkpoints": shuffle_checkpoint_options(defn["checkpoints"])
            })
        return submodules

    # Generic fallback for topics not yet in SUBMODULE_DEFINITIONS
    cheat = get_static_cheat_sheet(topic_id, video.get('title', 'Topic'))
    core = cheat.get('core', [])
    drills = cheat.get('drills', [])

    def pick(items, index, fallback):
        return items[index % len(items)] if items else fallback

    segments = [
        ("Module 1: Foundations", "Build conceptual clarity and key vocabulary.", 0, 420),
        ("Module 2: Deep Dive", "Strengthen understanding through mechanisms and flow.", 420, 900),
        ("Module 3: Exam Prep", "Focus on high-yield points, pitfalls, and drills.", 900, None)
    ]

    submodules = []
    for idx, (title, objective, start_sec, end_sec) in enumerate(segments):
        focus_line = pick(core, idx, f"Revise foundational concepts in {video.get('title', 'this topic')}.")
        drill_line = pick(drills, idx, "Attempt one quick recall drill before moving ahead.")
        submodules.append({
            "id": f"{topic_id}-m{idx+1}",
            "title": title,
            "objective": objective,
            "exam_angle": "",
            "video_id": video_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "checkpoints": [
                {"id": f"cp-{idx+1}-1", "trigger_pct": 30,
                 "question": "Which statement best matches this module focus?",
                 "options": [focus_line, "Skip basics and memorize final answers.", "Ignore conceptual flow.", "Avoid revision until final quiz."],
                 "correct_index": 0, "explanation": "This aligns with the current revision objective."},
                {"id": f"cp-{idx+1}-2", "trigger_pct": 65,
                 "question": "Best next revision action?",
                 "options": ["State one key concept and one edge case.", "Skip weak areas.", "Memorize without understanding.", "Avoid practice."],
                 "correct_index": 0, "explanation": "Active recall with edge cases improves retention."},
                {"id": f"cp-{idx+1}-3", "trigger_pct": 85,
                 "question": "Final checkpoint for this module:",
                 "options": [drill_line, "Do nothing until final quiz.", "Only rewatch without testing.", "Skip pitfall review."],
                 "correct_index": 0, "explanation": "Quick drills improve transfer and confidence."}
            ]
        })
        submodules[-1]["checkpoints"] = shuffle_checkpoint_options(submodules[-1]["checkpoints"])
    return submodules


def build_quiz_payload(user_id, topic_id, video, watch_time, study_group='experimental'):
    current_mastery = bkt_engine.get_mastery(user_id, topic_id)
    # Filtered by topic in the store: this is the one caller that needs the
    # per-question text, so narrowing it here keeps the heaviest read as
    # small as it can be.
    user_topic_attempts = quiz_repo.get_user_attempts(user_id, topic_id=topic_id)
    if user_topic_attempts:
        last_attempt = user_topic_attempts[-1]
        current_cluster = last_attempt.get('behavior_cluster', 'General Learner')
        current_speed = last_attempt.get('adaptation', {}).get('speed_label', 'Steady')
    else:
        current_cluster = 'General Learner'
        current_speed = 'Steady'

    from backend.adaptation.bandit_policy import bandit_adapter
    
    if study_group == 'control':
        current_difficulty = 'medium'
        current_speed = 'Steady'
        current_mastery = 0.5  # Static midpoint
        current_cluster = 'General Learner'
    else:
        current_difficulty = bandit_adapter.get_action(current_cluster, current_mastery)

    recent_question_texts = []
    for attempt in user_topic_attempts[-5:]:
        for q in attempt.get('question_results', []):
            text = q.get('text')
            if text:
                recent_question_texts.append(text)

    seen = set()
    avoid_questions = []
    for text in recent_question_texts:
        norm = text.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            avoid_questions.append(text)

    avoid_questions = avoid_questions[:30]

    quiz = quiz_gen.generate_quiz(
        topic_id,
        video['title'],
        video['video_id'],
        watch_time,
        difficulty=current_difficulty,
        mastery=current_mastery,
        cluster=current_cluster,
        speed_label=current_speed,
        avoid_questions=avoid_questions
    )

    question_count = len(quiz.get('questions', []))
    question_time_seconds = 15 if quiz.get('difficulty') == 'easy' else 12 if quiz.get('difficulty') == 'medium' else 10
    quiz['question_time_seconds'] = question_time_seconds
    quiz['hint_unlock_seconds'] = max(5, question_time_seconds // 2)
    quiz['topic_name'] = video['title']
    quiz['topic_id'] = topic_id
    quiz['question_count'] = question_count

    return quiz


def _is_admin(user_id):
    """Whether this account may read cohort-wide research data.

    Resolved from the stored record rather than the session, so revoking
    access takes effect on the next request instead of whenever the learner
    happens to log in again.
    """
    if not config.ADMIN_EMAILS:
        return False
    users = user_repo.get_all()
    if not isinstance(users, list):
        return False
    for user in users:
        if str(user.get('id')) == str(user_id):
            return str(user.get('email', '')).strip().lower() in config.ADMIN_EMAILS
    return False


CSRF_HEADER = 'X-CSRF-Token'
CSRF_COOKIE = 'csrf_token'
CSRF_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})


def _csrf_token():
    """This session's CSRF token, minted on first use."""
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


@app.before_request
def require_csrf_token():
    """Reject state-changing requests that do not echo the CSRF token.

    Double-submit: the authoritative token lives in the session, and a
    readable cookie carries a copy that `static/js/security_guard.js` echoes
    back in a header. A cross-origin page can make the browser send the
    cookie, but the same-origin policy stops it reading the value, so it
    cannot produce the matching header.

    Only authenticated requests are checked. An unauthenticated POST is
    login or registration, where there is no session to ride and nothing to
    forge on the user's behalf; requiring a token there would only mean
    rejecting the first request every new visitor makes. Those routes are
    covered by SameSite=Lax and their own rate limits.
    """
    if request.method in CSRF_SAFE_METHODS or 'user_id' not in session:
        return None

    expected = session.get('csrf_token')
    presented = request.headers.get(CSRF_HEADER, '')
    if expected and secrets.compare_digest(str(expected), str(presented)):
        return None

    return jsonify({
        'success': False,
        'message': 'Request could not be verified. Please reload the page.',
    }), 403


@app.after_request
def set_csrf_cookie(response):
    """Publish the token in a cookie the page's own JavaScript can read.

    Deliberately not HttpOnly: the whole point is that same-origin script can
    read it and an attacker's script cannot.
    """
    if 'user_id' in session:
        response.set_cookie(
            CSRF_COOKIE, _csrf_token(),
            secure=bool(app.config.get('SESSION_COOKIE_SECURE')),
            httponly=False, samesite='Lax', path='/')
    return response


@app.after_request
def set_security_headers(response):
    """Apply baseline security headers to every response.

    The Content-Security-Policy deliberately allows inline script and style:
    the templates carry 16 inline scripts and over 200 style attributes, so a
    strict policy would break the application rather than protect it. The
    valuable parts here are frame-ancestors, which stops the site being framed
    for clickjacking, and the restriction of script and frame sources to the
    origins actually used.

    HSTS is sent only over HTTPS. Sending it over plain HTTP is meaningless,
    and in local development it would pin localhost to HTTPS in the browser
    and make the app unreachable.
    """
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault(
        'Permissions-Policy',
        'geolocation=(), microphone=(), camera=(), payment=(), usb=()')
    response.headers.setdefault('Content-Security-Policy', '; '.join([
        "default-src 'self'",
        # s.ytimg.com is required: youtube.com/iframe_api injects its widget
        # script from there, and without it the video player never loads.
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://www.youtube.com https://s.ytimg.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: https:",
        "frame-src https://www.youtube.com https://www.youtube-nocookie.com",
        "connect-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]))

    if request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https':
        response.headers.setdefault(
            'Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    videos = video_repo.get_all_videos()
    # Figures derived from the curriculum rather than typed into the template,
    # where they went stale and advertised numbers that had not been true for
    # some time.
    return render_template('landing.html', courses=videos,
                           stats=curriculum_stats.landing_stats())

@app.route('/health')
def health():
    """Lightweight liveness/readiness check for uptime monitors and PaaS health checks.
    Deliberately avoids LLM calls or heavy DB work so it stays fast under frequent polling.
    """
    checks = {}
    status_code = 200

    try:
        checks['data_dir'] = os.path.isdir(os.path.dirname(config.VIDEOS_PATH))
        checks['videos_seed'] = os.path.isfile(config.VIDEOS_PATH)
        if not (checks['data_dir'] and checks['videos_seed']):
            status_code = 503
    except Exception as e:
        checks['error'] = str(e)
        status_code = 503

    return jsonify({
        'status': 'ok' if status_code == 200 else 'degraded',
        'checks': checks
    }), status_code

@app.route('/about')
def about():
    return jsonify({
        "name": "CogniLoop",
        "author": "Kavya Aggarwal",
        "description": "Closed-loop adaptive learning platform combining BKT, Thompson Sampling, and RAG.",
        # Neither of these is linked from the interface; they exist for
        # machine readers. A hardcoded "Operational" string told such a reader
        # nothing, since it was true whatever the system was doing - /health
        # is the endpoint that actually checks something.
        "health_endpoint": "/health"
    })

@app.route('/contact')
def contact():
    # No support_email here. This advertised support@cogniloop.com, an address
    # on a domain the project does not own, so anyone who wrote to it reached
    # nobody. The repository is a contact route that actually works.
    return jsonify({
        "project": "CogniLoop Research",
        "author": "Kavya Aggarwal",
        "repository": "https://github.com/OmegaKavya/CogniLoop"
    })

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json or {}
        email = data.get('email')
        password = data.get('password')

        account_key = f"account:{str(email).strip().lower()}"
        address_key = f"address:{_client_address()}"
        for key in (account_key, address_key):
            if not login_limiter.check(key):
                return jsonify({
                    'success': False,
                    'message': 'Too many failed attempts. Please try again later.'
                }), 429, {'Retry-After': str(login_limiter.retry_after(key))}

        user = user_repo.find_by_email(email)
        if user and verify_password(password, user.get('password')):
            # Only failures count toward the limit, so ordinary use is unaffected.
            login_limiter.reset(account_key)
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['study_group'] = user.get('study_group', 'experimental')
            return jsonify({'success': True})

        login_limiter.record(account_key)
        login_limiter.record(address_key)
        # Deliberately identical for an unknown account and a wrong password, so
        # the response cannot be used to discover which emails are registered.
        return jsonify({'success': False, 'message': 'Invalid credentials'})

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.json or {}
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        
        if not name or not email or not password:
            return jsonify({'success': False, 'message': 'Name, email, and password are required.'}), 400

        address_key = f"address:{_client_address()}"
        if not register_limiter.record(address_key):
            return jsonify({
                'success': False,
                'message': 'Too many sign-ups from this address. Please try again later.'
            }), 429, {'Retry-After': str(register_limiter.retry_after(address_key))}

        def build_user(new_id):
            return {
                'id': new_id,
                'name': name,
                'email': email,
                'password': hash_password(password),
                'study_group': random.choice(['control', 'experimental']),
                'created_at': datetime.now().isoformat()
            }

        new_user = user_repo.create(email, build_user)
        if new_user is None:
            return jsonify({'success': False, 'message': 'Email already registered'})

        session['user_id'] = new_user['id']
        session['user_name'] = new_user['name']
        return jsonify({'success': True})
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    videos = video_repo.get_all_videos()
    progress = progress_repo.get_all()
    user_progress = progress.get(user_id, {})

    for video in videos:
        video_p = user_progress.get(video['id'], {})
        video['progress'] = video_p.get('watch_percentage', 0)
    
    # Without question_results: this page shows scores, mastery and
    # insight summaries, never the questions themselves.
    user_attempts = quiz_repo.get_user_attempts(user_id, include_responses=False)
    
    user_attempts.sort(key=lambda x: x['timestamp'])
    
    topic_counters = {}
    temp_labels = []
    for a in user_attempts:
        topic = a.get('topic_id', 'Quiz').upper()
        topic_counters[topic] = topic_counters.get(topic, 0) + 1
        temp_labels.append(f"{topic} #{topic_counters[topic]}")
    
    relevant_attempts = user_attempts[-10:]
    mastery_history = [round(a['mastery'] * 100, 2) for a in relevant_attempts]
    mastery_labels = temp_labels[-10:]

    # Per-course mastery data for the course-selector chart
    mastery_by_course = {}
    course_counters = {}
    for a in user_attempts:
        tid = a.get('topic_id', 'unknown')
        course_counters[tid] = course_counters.get(tid, 0) + 1
        mastery_by_course.setdefault(tid, {'labels': [], 'values': []})
        mastery_by_course[tid]['labels'].append(f"#{course_counters[tid]}")
        mastery_by_course[tid]['values'].append(round(a['mastery'] * 100, 2))

    topic_map = {v['id']: v['title'] for v in videos}
    topic_heatmap_rows = build_topic_heatmap_rows(user_attempts, topic_map)
    review_rows = build_review_rows(user_attempts, topic_map)
    recent_reviews = review_rows[:5]
    latest_ai_insight = recent_reviews[0].get('insight_summary') if recent_reviews else None
    latest_review_by_topic = {}
    for row in review_rows:
        topic_id = row.get('topic_id')
        if topic_id and topic_id not in latest_review_by_topic and row.get('attempt_id'):
            latest_review_by_topic[topic_id] = row.get('attempt_id')
    
    latest_speed = "Standard"
    latest_cluster = "General Learner"
    speed_message = "Keep up the consistent effort!"
    
    if user_attempts:
        latest_attempt = user_attempts[-1]
        latest_speed = latest_attempt.get('adaptation', {}).get('speed_label', 'Standard')
        latest_cluster = latest_attempt.get('behavior_cluster', 'General Learner')
        
        if latest_speed == 'Fast':
            speed_message = "You are moving quickly through concepts with high accuracy!"
        elif latest_speed == 'Slow':
            speed_message = "Taking your time is great for deep understanding. Keep going!"
        else:
            speed_message = "You are maintaining a steady and optimal learning pace."

    # Gamification: XP & Streak calculation
    total_quizzes = len(user_attempts)
    user_xp = sum(a.get('score', 0) * 10 for a in user_attempts)
    bkt_states = bkt_engine.get_all_states().get(user_id, {})

    # Skill tree. `started` distinguishes a measured estimate from the prior.
    #
    # This previously fell back to 0.3 for any topic with no state and rendered
    # it as "30.0% BKT Mastery" in red. That number is the model's prior, not a
    # measurement of the learner - so a brand-new learner opened the dashboard
    # to four red failing scores for work they had not done yet. It was both
    # wrong and discouraging.
    def _node(topic_id, name, prereq):
        raw = bkt_states.get(topic_id)
        described = mastery_scale.describe(raw)
        return {
            "id": topic_id,
            "name": name,
            "prereq": prereq,
            "started": raw is not None,
            "mastery": round((raw if raw is not None else config.BKT_DEFAULTS["prior"]) * 100, 1),
            "band": described["label"],
            "band_meaning": described["meaning"],
        }

    skill_tree_nodes = [
        _node("os", "Operating Systems", None),
        _node("ds", "Data Structures", None),
        _node("dbms", "DBMS", "ds"),
        _node("cn", "Computer Networks", "os"),
    ]

    return render_template('dashboard.html', 
                         user_name=session['user_name'], 
                         videos=videos,
                         mastery_history=mastery_history,
                         mastery_labels=mastery_labels,
                         mastery_by_course=mastery_by_course,
                         learning_speed=latest_speed,
                         learning_cluster=latest_cluster,
                         speed_message=speed_message,
                         recent_reviews=recent_reviews,
                         latest_ai_insight=latest_ai_insight,
                         latest_review_by_topic=latest_review_by_topic,
                         topic_heatmap_rows=topic_heatmap_rows,
                         user_xp=user_xp,
                         # A learner who has taken no quizzes has no streak.
                         # This used to floor at 1, so an account minutes old
                         # was congratulated on a "1 Day Streak".
                         user_streak=min(total_quizzes, 7),
                         total_quizzes=total_quizzes,
                         skill_tree_nodes=skill_tree_nodes,
                         mastery_scale_note=mastery_scale.scale_note())

@app.route('/progress')
def progress_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    # Without question_results: this page shows scores, mastery and
    # insight summaries, never the questions themselves.
    user_attempts = quiz_repo.get_user_attempts(user_id, include_responses=False)
    videos = video_repo.get_all_videos()
    
    topic_map = {v['id']: v['title'] for v in videos}
    for attempt in user_attempts:
        attempt['topic_name'] = topic_map.get(attempt['topic_id'], attempt['topic_id'])

    # Summary statistics
    total_quizzes = len(user_attempts)
    avg_score = round(sum(a.get('score', 0) for a in user_attempts) / total_quizzes, 1) if total_quizzes else 0
    total_time = round(sum(a.get('total_time', 0) for a in user_attempts), 1)

    # Per-course live mastery from BKT
    bkt_states = bkt_engine.get_all_states().get(user_id, {})
    course_mastery = {tid: round(val * 100, 1) for tid, val in bkt_states.items()}

    # Available courses for filter tabs
    course_ids = sorted(set(a.get('topic_id') for a in user_attempts if a.get('topic_id')))

    return render_template('progress.html',
                         attempts=user_attempts,
                         total_quizzes=total_quizzes,
                         avg_score=avg_score,
                         total_time=total_time,
                         course_mastery=course_mastery,
                         course_ids=course_ids,
                         topic_map=topic_map)

@app.route('/video/<topic_id>')
def video_page(topic_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    videos = video_repo.get_all_videos()
    video = next((v for v in videos if v['id'] == topic_id), None)
    if not video:
        return redirect(url_for('dashboard'))

    submodules = build_topic_submodules(video)
    return render_template('video.html', video=video, submodules=submodules)

@app.route('/export-cheat-sheet/<attempt_id>')
def export_cheat_sheet(attempt_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    # One attempt by id, scoped to its owner, rather than every attempt the
    # learner has ever made so that one of them can be picked out in Python.
    attempt = quiz_repo.get_attempt(user_id, attempt_id) or quiz_repo.latest_attempt(user_id)

    if not attempt:
        return redirect(url_for('dashboard'))

    topic_id = attempt.get('topic_id', 'os')
    topic_name = attempt.get('topic_name') or topic_id.upper()
    attempt['topic_name'] = topic_name

    cheat_sheet = get_static_cheat_sheet(topic_id, topic_name)
    ai_insights = attempt.get('ai_insights', {})

    return render_template('export_cheat_sheet.html',
                         attempt=attempt,
                         cheat_sheet=cheat_sheet,
                         ai_insights=ai_insights)

from backend.adaptation.micro_pattern import mp_manager

def refine_insights_in_background(user_id, attempt_id, topic_name, score,
                                  mastery, question_results):
    """Ask the model to rewrite an attempt's advice, after the response.

    Why this is not in the request: three providers are tried in turn, each
    with its own timeout, so an unreachable service could hold a submission for
    minutes. Nothing the learner is shown depends on it - the score, the
    mastery estimate, the behaviour cluster and the next difficulty are all
    computed locally, and the deterministic advice stored with the attempt is
    real content rather than a placeholder. The model only ever replaces that
    text with a better-written version, which appears on the review page the
    next time it is opened.

    A daemon thread, so a worker shutting down does not wait on it. If the
    process dies first the attempt simply keeps the deterministic advice, which
    is why this writes nothing until it has a result worth writing.

    The destination is bound here, before the thread starts, rather than read
    off the singleton when the write happens. The repository resolves its store
    from `file_path` on every access, so a thread that outlives the request
    would otherwise write wherever that attribute points by then, which is not
    necessarily where the attempt it is updating was stored.
    """
    destination = QuizAttemptRepository(quiz_repo.file_path)

    def run():
        try:
            insights = insights_engine.model_insights(
                topic_name, score, mastery, question_results)
            if insights:
                destination.set_insights(user_id, attempt_id, insights)
        except Exception as exc:
            # Never surfaced to the learner: the attempt already has usable
            # advice, so a failure here is a missed improvement, not an error.
            print(f"[Insights] background refinement failed for {attempt_id}: {exc}")

    threading.Thread(target=run, daemon=True,
                     name=f"insights-{attempt_id}").start()


from backend.adaptation.recommendation import recommender
from backend.quiz.quiz_generator import quiz_gen
from backend.quiz.quiz_evaluator import evaluator
from backend.quiz.quiz_insights import insights_engine
from backend.bkt.bkt_engine import bkt_engine
from backend.adaptation.bandit_policy import bandit_adapter


@app.route('/api/video-track', methods=['POST'])
def video_track():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    data = request.json
    user_id = session['user_id']
    video_id = data.get('topic_id')
    
    interaction_data = {
        "pause_count": data.get('pause_count', 0),
        "rewatch_count": data.get('rewatch_count', 0),
        "skip_ratio": data.get('skip_ratio', 0),
        "watch_percentage": data.get('watch_percentage', 0)
    }
    
    success = mp_manager.log_interaction(user_id, video_id, interaction_data)
    
    progress_data = {
        "last_position": data.get('last_time', 0),
        "watch_percentage": data.get('watch_percentage', 0),
        "timestamp": datetime.now().isoformat()
    }
    progress_repo.save_progress(user_id, video_id, progress_data)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Logging failed'}), 500

@app.route('/api/user-progress/<video_id>', methods=['GET'])
def get_user_progress(video_id):
    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    
    user_id = session['user_id']
    user_progress = progress_repo.get_progress(user_id, video_id)
    return jsonify({
        'success': True,
        'last_position': user_progress.get('last_position', 0),
        'watch_percentage': user_progress.get('watch_percentage', 0)
    })

@app.route('/quiz/<topic_id>')
def quiz_page(topic_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    videos = video_repo.get_all_videos()
    video = next((v for v in videos if v['id'] == topic_id), None)
    if not video:
        return redirect(url_for('dashboard'))

    cheat_sheet = get_static_cheat_sheet(topic_id, video['title'])
    return render_template(
        'quiz.html',
        loading=True,
        topic_id=topic_id,
        topic_name=video['title'],
        static_cheat_sheet=cheat_sheet
    )


@app.route('/api/quiz-data/<topic_id>', methods=['GET'])
def api_quiz_data(topic_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    videos = video_repo.get_all_videos()
    video = next((v for v in videos if v['id'] == topic_id), None)
    if not video:
        return jsonify({'success': False, 'message': 'Topic not found'}), 404

    user_id = session['user_id']
    study_group = session.get('study_group', 'experimental')
    user_video_progress = progress_repo.get_progress(user_id, topic_id)
    watch_time = user_video_progress.get('last_position', 0)

    quiz = build_quiz_payload(user_id, topic_id, video, watch_time, study_group)

    # The quiz, answer key included, stays on the server. The client gets an
    # opaque token and a redacted copy. It previously received the whole object
    # twice over - once in this response body and once in the session cookie,
    # which is signed but not encrypted and so is readable by its holder.
    quiz_token = active_quiz_store.issue(user_id, quiz)

    return jsonify({
        'success': True,
        'quiz': public_view(quiz),
        'quiz_token': quiz_token,
        'static_cheat_sheet': get_static_cheat_sheet(topic_id, video['title'])
    })



@app.route('/api/quiz-submit', methods=['POST'])
def quiz_submit():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    data = request.json
    user_id = session['user_id']
    topic_id = data.get('topic_id')
    responses = data.get('responses', [])

    # Single-use: consuming the token stops one issued quiz being replayed to
    # farm repeated mastery updates from the same set of questions.
    quiz = active_quiz_store.consume(data.get('quiz_token'), user_id)
    if not quiz:
        return jsonify({'success': False, 'message': 'Quiz session expired. Please refresh the page.'}), 400

    # The tier the server actually served, from the server's own copy of the
    # quiz. Reading this from the request body let the client name the
    # difficulty its own mastery update would be computed with - selecting
    # `hard` swaps guess/slip from 0.30/0.05 to 0.10/0.15 and inflates the
    # posterior - and name the bandit arm that would be credited for the result.
    current_difficulty = quiz.get('difficulty', 'medium')

    eval_result = evaluator.evaluate(quiz, responses)
    if not eval_result:
        return jsonify({'success': False, 'message': 'Evaluation error'}), 500
    
    score = eval_result['score']
    avg_time = eval_result['avg_time']
    
    # Still keep a speed label for UI purposes, but use bandit for actual difficulty
    speed_label = speed_adapter.speed_label(avg_time)
    adaptation = {
        "speed_label": speed_label,
        "new_difficulty": current_difficulty # Recorded for historical purposes
    }
    
    study_group = session.get('study_group', 'experimental')
    
    is_correct_overall = score >= 70
    new_mastery = bkt_engine.update_mastery(user_id, topic_id, is_correct_overall, difficulty=current_difficulty)
    
    cluster = mp_manager.predict_cluster(
        mp_manager.latest_interaction(user_id, topic_id))
    
    if study_group == 'experimental':
        # Update Bandit Policy
        bandit_adapter.update_policy(cluster, new_mastery, current_difficulty, score)
        recommendation = recommender.get_recommendation(score, new_mastery, speed_label, cluster)
    else:
        # Static control group logic
        recommendation = "Continue reviewing the material sequentially."
        
    videos = video_repo.get_all_videos()
    video = next((v for v in videos if v['id'] == topic_id), {'title': topic_id})
    
    # Deterministic insights now; the model version is produced after the
    # response has gone out. See refine_insights_in_background.
    ai_insights = insights_engine.generate_insights(
        video.get('title', topic_id),
        score,
        round(new_mastery, 2),
        eval_result.get('question_results', []),
        topic_id=topic_id,
        use_model=False
    )

    answer_map = {
        str(r.get('question_id')): {
            'selected_answer': r.get('selected_answer'),
            'time_taken': r.get('time_taken'),
            'used_hint': r.get('used_hint', False)
        }
        for r in responses
    }
    reviewed_questions = []
    for q_res in eval_result.get('question_results', []):
        qid = str(q_res.get('question_id'))
        q_data = next((q for q in quiz.get('questions', []) if str(q.get('id')) == qid), {})
        user_data = answer_map.get(qid, {})
        reviewed_questions.append({
            'id': qid,
            'text': q_data.get('text'),
            'options': q_data.get('options', []),
            'correct_answer': q_data.get('answer'),
            'selected_answer': user_data.get('selected_answer'),
            'is_correct': q_res.get('is_correct', False),
            'feedback': q_res.get('feedback', ''),
            'hint': q_data.get('hint', ''),
            'used_hint': user_data.get('used_hint', False),
            'time_taken': user_data.get('time_taken', q_res.get('time_taken', 0))
        })

    attempt_id = f"{user_id}-{uuid.uuid4().hex[:10]}"

    
    attempt_log = {
        "attempt_id": attempt_id,
        "user_id": user_id,
        "topic_id": topic_id,
        "topic_name": video.get('title', topic_id),
        "timestamp": datetime.now().isoformat(),
        "score": score,
        "avg_time": avg_time,
        "total_time": eval_result.get('total_time', 0),
        "adaptation": adaptation,
        "mastery": new_mastery,
        "behavior_cluster": cluster,
        "recommendation": recommendation,
        "quiz_meta": {
            "difficulty": quiz.get('difficulty', current_difficulty),
            "num_questions": len(quiz.get('questions', [])),
            # The key written by build_quiz_payload is question_time_seconds.
            # Reading 'timer_seconds' meant this logged 0 on every attempt.
            "timer_seconds": quiz.get('question_time_seconds', 0),
            "hint_unlock_seconds": quiz.get('hint_unlock_seconds', 0)
        },
        "question_results": reviewed_questions,
        "ai_insights": ai_insights
    }
    
    quiz_repo.add_attempt(attempt_log)

    refine_insights_in_background(
        user_id, attempt_id, video.get('title', topic_id),
        score, round(new_mastery, 2), reviewed_questions)
    
    # What the policy will serve next, and the reason. The system adapts
    # silently otherwise: a learner has no way to tell that difficulty is being
    # chosen for them rather than fixed, which is the one thing that makes this
    # different from a static quiz app.
    if study_group == 'experimental':
        next_difficulty = bandit_adapter.get_action(cluster, new_mastery)
        # Counted in the store. The attempt just written is included, which is
        # what the message below means by "attempts on this topic".
        topic_attempts = quiz_repo.count_user_attempts(user_id, topic_id=topic_id)

        # Explain the mechanism, not a story about the learner.
        #
        # An earlier version said "you are scoring well enough to be stretched"
        # whenever the tier went up. That is not why the tier went up: Thompson
        # sampling draws from each arm's posterior, so early on a change is
        # usually exploration, and the sentence was attributing a judgement to
        # the policy that the policy had not made. A learner who had just
        # scored 20% was told they were doing well.
        if topic_attempts < 3:
            why = (f"Trying {next_difficulty} next. With "
                   f"{topic_attempts} attempt{'' if topic_attempts == 1 else 's'} "
                   f"on this topic, the system is still sampling levels to find "
                   f"which one suits you - expect it to move around at first.")
        elif next_difficulty == current_difficulty:
            why = (f"Staying at {next_difficulty}. On the evidence so far this "
                   f"level is producing your best results.")
        elif config.DIFFICULTY_TIERS.index(next_difficulty) > config.DIFFICULTY_TIERS.index(current_difficulty):
            why = (f"Moving up to {next_difficulty}. Across your attempts, the "
                   f"harder level is doing at least as well for you as this one.")
        else:
            why = (f"Easing to {next_difficulty}. Across your attempts, the "
                   f"easier level has been producing better outcomes.")
    else:
        next_difficulty = current_difficulty
        why = "Your group follows a fixed curriculum, so the difficulty does not change."

    return jsonify({
        'success': True, 
        'score': score,
        'adaptation': adaptation,
        'mastery': round(new_mastery, 2),
        'cluster': cluster,
        'results': eval_result['question_results'],
        'recommendation': recommendation,
        'attempt_id': attempt_id,
        'ai_insights': ai_insights,
        'served_difficulty': current_difficulty,
        'next_difficulty': next_difficulty,
        'next_difficulty_reason': why
    })


@app.route('/quiz-review')
def quiz_review_list():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    # Without question_results: this page shows scores, mastery and
    # insight summaries, never the questions themselves.
    user_attempts = quiz_repo.get_user_attempts(user_id, include_responses=False)
    videos = video_repo.get_all_videos()
    topic_map = {v['id']: v['title'] for v in videos}
    review_rows = build_review_rows(user_attempts, topic_map)

    return render_template('quiz_review.html', review_rows=review_rows, selected_attempt=None)


@app.route('/quiz-review/<attempt_id>')
def quiz_review_page(attempt_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    # The sidebar lists every attempt but renders only summary fields; the
    # one attempt actually being read is fetched whole, by id.
    user_attempts = quiz_repo.get_user_attempts(user_id, include_responses=False)
    videos = video_repo.get_all_videos()
    topic_map = {v['id']: v['title'] for v in videos}

    review_rows = build_review_rows(user_attempts, topic_map)
    selected_attempt = quiz_repo.get_attempt(user_id, attempt_id)

    if not selected_attempt:
        return redirect(url_for('quiz_review_list'))

    return render_template('quiz_review.html', review_rows=review_rows, selected_attempt=selected_attempt)

from backend.analytics.metrics import analytics_engine

@app.route('/api/research-analytics')
def research_analytics():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    # Cohort-wide data: every learner's study group and aggregate performance.
    # The allowlist is empty unless ADMIN_EMAILS is configured, so this fails
    # closed rather than serving the cohort to whoever asks.
    #
    # The address is read from the stored record rather than the session, so
    # it reflects the account as it is now and never has to travel in the
    # cookie.
    if not _is_admin(session['user_id']):
        return jsonify({'success': False, 'message': 'Forbidden'}), 403

    report = analytics_engine.generate_experiment_report()
    return jsonify({
        'success': True,
        'report': report
    })

if __name__ == '__main__':
    app.run(
        debug=os.environ.get('FLASK_DEBUG', '1') == '1',
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '5001')),
    )
