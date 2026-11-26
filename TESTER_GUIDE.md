# Testing CogniLoop

Thanks for doing this.

CogniLoop is an adaptive learning system I built. It changes the difficulty of
your next quiz based on how you answered the last one. It has only ever been
tested on simulated learners. I need real ones.

**Getting answers wrong is useful.** Possibly more useful than getting them
right.

---

## Before you start: one line of consent

By taking part you're agreeing that your quiz answers, response times and
scores can be used in my research, including in an academic paper, **reported
only as anonymous aggregates, never individually and never by name**.

**One thing you should know:** to generate questions and write your feedback,
the system sends quiz content and your answers to an external AI provider
(Groq). **Your name, email and account are never sent**, only the question
text, which option you picked, and how long you took. If you'd rather that
didn't happen, don't take part, and no hard feelings.

You can stop at any point, and ask me to delete everything, without giving a
reason. Just tell me: I have a script that removes your account, attempts,
progress and learning estimates, and confirms nothing is left. The only thing
it can't take back is your small share in two group-level statistics,
computed across everyone, that hold no name, email or id.

---

## Pick your track

| | **Track A: one sitting** | **Track B: contributor** |
|---|---|---|
| Time | 15 minutes, once | 15 minutes × 3, over ~2 weeks |
| What it gives me | Response-time data, bug reports, question quality | All of that **plus** whether people actually learn |
| Pick this if | You can spare one block | You're willing to come back twice |

**Track B is worth far more to me**, because improvement can only be measured
across sessions. But Track A is genuinely useful, so don't pick B unless you'll
actually return.

---

## Setup (both tracks)

**1. Open the link now:** https://cogniloop-2svo.onrender.com

First load can take a minute, because the free server sleeps. Leave it open while you
read on.

**2. Sign up.** Any email, never contacted or shared. **Use a throwaway
password, not a real one.**

**3. Pick ONE topic:**

| If you | Pick |
|---|---|
| Know a CS subject | Data Structures, Operating Systems, DBMS, or Computer Networks |
| Don't, or aren't sure | **Quantitative Aptitude** |

Quantitative Aptitude needs no background: percentages, ratios, speed and
distance, time and work. School level. **If in doubt, pick this.**

**Do not switch topics, ever, including between sessions.** The system adapts
to you per topic. Switching restarts it from zero and wastes everything.

---

## Track A: one sitting

Take the same quiz **4 times in a row**. Each run is 8 to 10 questions,
2 to 3 minutes. Your first one is labelled **Starting quiz**.

Then press **Take the final check quiz** on the results page and do that one
too. **This last one is the one that counts most**: without it, your runs
can't be measured.

Glance at your results page between runs. That's it. Then answer the four
questions at the bottom of this page.

---

## Track B: contributor

**Session 1 (today):** take the quiz **3 times**. The first is labelled
**Starting quiz**: that's your starting point. The results page will offer
**Take the final check quiz** after your third run. **Don't take it yet**: it
can be taken only once, and in Track B it belongs at the end of session 3.

**Then, before session 2:** spend 10 to 15 minutes on that topic's modules inside
the app (the videos and notes on the topic page). This matters: I'm testing
whether the system teaches, so please learn from *it*, not from elsewhere.

**Session 2 (2 to 4 days later):** take the quiz **3 times**, and again skip
the final check quiz.

**Session 3 (about a week after that):** take the quiz **3 times**, then press
**Take the final check quiz** on the results page and do that one too. It's
the one that counts most. Then answer the four questions below.

Same login, same topic, every time. If you miss the timing by a few days it's
fine. Just don't stop halfway, because a half-finished Track B tells me less
than a completed Track A.

---

## How to answer (both tracks)

**Answer exactly as you normally would.** Please do **not**:

- rush to finish quicker
- get things wrong on purpose to test it
- look anything up mid-quiz

If you don't know, guess and move on, or let the timer run out. Both are real
and both are useful.

---

## What I'm actually measuring

Three things. None of them is whether you did well.

**1. How long you take on each question.** The main one. The system tries to
tell apart: you guessed instantly, you worked at it and got it wrong, or you
knew it. The cutoffs between those are currently numbers I made up. Your
timings replace my guesses with real ones.

→ *This is why rushing ruins it.* A fast wrong answer is recorded as a guess.
Speed up to save me time, and you'll be logged as guessing on questions you
were genuinely thinking about.

**2. Whether difficulty adaptation does anything.** The system picks your next
difficulty from how you did. Three or four runs is the minimum before that
shows up; below that it's deliberately still experimenting. Your **starting
quiz** and **final check quiz** are the same kind of quiz for everyone, whatever
group you're in. Comparing those two is what tells me whether you learned, not
just whether you were given easier questions.

→ *This is why one quiz is no use, and why switching topics wastes it.*

**3. Whether the generated questions are any good.** Questions are written by a
model, fresh for each quiz (your starting and final check quizzes stay the same
if you reload them, and a few may come from a short hand-written set when the
model is unavailable). Nobody outside my own testing has judged them.

→ *This is why "question 4 was nonsense" is genuinely valuable.*

**Track B adds a fourth:** whether your scores move across sessions. That is
the only question that cannot be answered in a single sitting, and it's the
one I care most about.

**What I'm not measuring: you.** There's no pass mark. A session where you got
everything wrong is exactly as useful as one where you aced it.

---

## Tell me four things at the end

One line each.

1. **Did the difficulty change** as you went, or feel flat?
2. **Were the questions sensible?** Say if any were nonsense or wrong.
3. **Was the advice after each quiz useful, or generic filler?**
4. **Anything that broke, confused or annoyed you.** Especially small things.

*Track B, also:* did it feel easier by session 3, or the same?

---

## Privacy

Your answers, timings and scores, nothing else. Your email is a login and is
never contacted.

Your answers pass through an external AI provider (Groq) to be graded and to
generate feedback, **without your name or email attached**. Nothing goes
anywhere else, and no one but me sees your individual results.

Say the word and I delete everything tied to you.

## If something goes wrong

- **Won't load first time** → wait a minute, refresh. Server waking up.
- **"Quiz session expired"** → refresh, start the quiz again.
- **Anything else** → stop, tell me what you saw. A bug you found beats a quiz
  you finished.

Thanks. This is the part I can't do alone.
