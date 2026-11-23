#!/usr/bin/env python3
"""Remove one participant and everything recorded about them.

Why this exists
---------------
TESTER_GUIDE.md tells participants: "Say the word and I delete all of it."
That promise was made before any mechanism existed to keep it. The repository
layer's `delete()` operates on dict-shaped documents while `users` is a list,
and nothing at all touched attempts, progress, BKT state or behaviour logs. A
request would have meant hand-editing JSON in production.

A consent promise the system cannot honour is worse than one not made, and it
is the first thing an ethics reviewer asks about.

What it removes, by document:

  users           the account row              matched on id or email
  quiz_attempts   every attempt                matched on user_id
  user_progress   the per-topic progress map   keyed by user id
  bkt_states      the mastery estimates        keyed by user id
  micro_patterns  the behaviour log            matched on user_id

What it cannot remove, and why that is disclosed rather than hidden:

  bandit_q_table  the policy posterior is an AGGREGATE over all learners,
                  keyed by behaviour cluster and mastery band, not by person.
                  One participant's contribution cannot be subtracted from it
                  without replaying every other participant's history. It
                  holds no identifier and nothing about an individual can be
                  recovered from it. If a participant insists, the honest
                  options are to reset the table or to say plainly that this
                  one aggregate retains an unattributable statistical trace.

Usage:
    python3 scripts/delete_participant.py --email someone@example.com --dry-run
    python3 scripts/delete_participant.py --email someone@example.com --confirm

Runs against whatever DATABASE_URL points at, or the local JSON files when it
is unset. It prints what it will remove and does nothing without --confirm.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.storage import open_store  # noqa: E402

DOCUMENTS = {
    "users": "data/users.json",
    "quiz_attempts": "data/quiz_attempts.json",
    "user_progress": "data/user_progress.json",
    "bkt_states": "data/bkt_states.json",
    "micro_patterns": "data/micro_patterns.json",
}


def resolve_user(email, user_id):
    users = open_store(DOCUMENTS["users"], default=list).read()
    if not isinstance(users, list):
        sys.exit("users document is not a list; refusing to guess")
    for user in users:
        if email and str(user.get("email", "")).lower() == email.lower():
            return user
        if user_id and str(user.get("id")) == str(user_id):
            return user
    return None


def count_matches(uid):
    found = {}
    attempts = open_store(DOCUMENTS["quiz_attempts"], default=list).read()
    found["quiz_attempts"] = sum(
        1 for a in attempts if isinstance(a, dict) and str(a.get("user_id")) == uid)
    patterns = open_store(DOCUMENTS["micro_patterns"], default=list).read()
    found["micro_patterns"] = sum(
        1 for p in patterns if isinstance(p, dict) and str(p.get("user_id")) == uid)
    for name in ("user_progress", "bkt_states"):
        doc = open_store(DOCUMENTS[name], default=dict).read()
        found[name] = 1 if isinstance(doc, dict) and uid in doc else 0
    return found


def delete(uid):
    removed = {}

    def drop_from_list(path, key):
        store = open_store(path, default=list)
        count = {"n": 0}

        def mutate(rows):
            kept = []
            for row in rows:
                if isinstance(row, dict) and str(row.get(key)) == uid:
                    count["n"] += 1
                    continue
                kept.append(row)
            return kept

        store.update_replacing(mutate, default=list)
        return count["n"]

    removed["quiz_attempts"] = drop_from_list(DOCUMENTS["quiz_attempts"], "user_id")
    removed["micro_patterns"] = drop_from_list(DOCUMENTS["micro_patterns"], "user_id")
    removed["users"] = drop_from_list(DOCUMENTS["users"], "id")

    for name in ("user_progress", "bkt_states"):
        store = open_store(DOCUMENTS[name], default=dict)
        count = {"n": 0}

        def mutate(doc, _c=count):
            if isinstance(doc, dict) and uid in doc:
                doc.pop(uid)
                _c["n"] += 1
            return doc

        store.update(mutate)
        removed[name] = count["n"]

    return removed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email")
    ap.add_argument("--user-id")
    ap.add_argument("--confirm", action="store_true",
                    help="actually delete; without it nothing is written")
    args = ap.parse_args()

    if not args.email and not args.user_id:
        ap.error("give --email or --user-id")

    backend = "Postgres" if os.environ.get("DATABASE_URL", "").strip() else "local JSON files"
    print(f"Backend: {backend}\n")

    user = resolve_user(args.email, args.user_id)
    if not user:
        sys.exit("No such participant. Nothing was changed.")

    uid = str(user.get("id"))
    print(f"Participant: id={uid}  email={user.get('email')}  "
          f"group={user.get('study_group')}  joined={user.get('created_at', '?')[:10]}")
    print("\nWould remove:")
    for name, n in count_matches(uid).items():
        print(f"  {name:<16} {n}")
    print(f"  {'users':<16} 1")
    print("\nNot removable: bandit_q_table holds an aggregate posterior with no "
          "identifier in it; see the module docstring.")

    if not args.confirm:
        print("\nDry run. Re-run with --confirm to delete.")
        return 0

    removed = delete(uid)
    print("\nDeleted:")
    for name, n in removed.items():
        print(f"  {name:<16} {n}")

    if resolve_user(args.email, uid) is not None:
        sys.exit("\nFAILED: the account is still present after deletion.")
    leftover = {k: v for k, v in count_matches(uid).items() if v}
    if leftover:
        sys.exit(f"\nFAILED: records remain: {leftover}")
    print("\nVerified: nothing for this participant remains in any document.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
