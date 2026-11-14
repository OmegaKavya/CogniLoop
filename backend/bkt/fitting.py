"""
Expectation-maximisation fitting of Bayesian Knowledge Tracing parameters.

Why this exists
---------------
BKT parameters (prior, learn, guess, slip) are properties of a skill and its
item pool. They must be estimated from response data; choosing them by hand
makes the mastery estimate systematically wrong, and every downstream decision
inherits that error.

The project previously depended on pyBKT for this. pyBKT 1.4.3 raises on import
against scikit-learn >= 1.8 (its metric-probing code calls `.dtype` on a plain
list), and the caller swallowed the exception, so parameter fitting was skipped
silently and the hardcoded defaults were used in production. This module
removes that dependency.

Model
-----
Standard two-state BKT, a hidden Markov model with no forgetting:

    states       0 = not mastered, 1 = mastered
    initial      P(state_1 = 1) = prior
    transition   P(0 -> 1) = learn,  P(1 -> 0) = 0
    emission     P(correct | 0) = guess,  P(correct | 1) = 1 - slip

Parameters are fitted by Baum-Welch over per-learner response sequences.

Identifiability and degenerate fits
-----------------------------------
BKT is well known to admit degenerate maximum-likelihood solutions in which the
latent state loses its intended meaning -- most notoriously when guess + slip
approaches or exceeds 1, so that "mastery" predicts failure. Such a fit can
have a higher likelihood than a sensible one while being useless for
instruction.

Two safeguards apply. First, guess and slip are constrained below 0.5. Second,
a fit whose parameters rest on a constraint boundary is reported as degenerate:
a parameter pinned to its bound means the likelihood was still improving
against the constraint, so that parameter is not identified by the data.
Callers are expected to fall back to configured defaults rather than deploy a
degenerate fit, because a confidently wrong parameter is worse than an honest
default.

EM converges only to a local optimum, so fitting uses several randomised
restarts and keeps the best non-degenerate solution.
"""

import math
import random

import numpy as np

DEFAULT_MAX_GUESS = 0.45
DEFAULT_MAX_SLIP = 0.45
DEFAULT_RESTARTS = 5
_EPS = 1e-6
_BOUNDARY_TOL = 1e-3


class BKTFitResult:
    __slots__ = ("prior", "learn", "guess", "slip", "log_likelihood",
                 "iterations", "converged", "n_sequences", "n_responses",
                 "degenerate", "degeneracy_reasons", "restarts")

    def __init__(self, prior, learn, guess, slip, log_likelihood,
                 iterations, converged, n_sequences, n_responses,
                 degenerate=False, degeneracy_reasons=(), restarts=1):
        self.prior = prior
        self.learn = learn
        self.guess = guess
        self.slip = slip
        self.log_likelihood = log_likelihood
        self.iterations = iterations
        self.converged = converged
        self.n_sequences = n_sequences
        self.n_responses = n_responses
        self.degenerate = degenerate
        self.degeneracy_reasons = list(degeneracy_reasons)
        self.restarts = restarts

    def as_dict(self):
        return {
            "prior": self.prior,
            "learn": self.learn,
            "guess": self.guess,
            "slip": self.slip,
            "log_likelihood": self.log_likelihood,
            "iterations": self.iterations,
            "converged": self.converged,
            "n_sequences": self.n_sequences,
            "n_responses": self.n_responses,
            "degenerate": self.degenerate,
            "degeneracy_reasons": self.degeneracy_reasons,
            "restarts": self.restarts,
        }

    def __repr__(self):
        flag = " DEGENERATE" if self.degenerate else ""
        return (f"BKTFitResult(prior={self.prior:.4f}, learn={self.learn:.4f}, "
                f"guess={self.guess:.4f}, slip={self.slip:.4f}, "
                f"n={self.n_responses}{flag})")


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def degeneracy_reasons(prior, learn, guess, slip,
                       max_guess=DEFAULT_MAX_GUESS, max_slip=DEFAULT_MAX_SLIP):
    """Return the reasons a parameter set should not be trusted; empty if sound."""
    reasons = []
    if guess + slip >= 1.0:
        reasons.append("guess+slip>=1 (latent state does not predict performance)")
    if guess >= max_guess - _BOUNDARY_TOL:
        reasons.append("guess pinned at bound")
    if slip >= max_slip - _BOUNDARY_TOL:
        reasons.append("slip pinned at bound")
    for name, value in (("prior", prior), ("learn", learn),
                        ("guess", guess), ("slip", slip)):
        if value <= _BOUNDARY_TOL:
            reasons.append(f"{name} pinned at 0")
        elif value >= 1.0 - _BOUNDARY_TOL:
            reasons.append(f"{name} pinned at 1")
    return reasons


def _forward_backward(obs, prior, learn, guess, slip):
    """Scaled forward-backward for one sequence.

    Returns (gamma, xi_01, log_likelihood) where gamma[t, k] is
    P(state_t = k | obs) and xi_01[t] is P(state_t = 0, state_{t+1} = 1 | obs).
    """
    n = len(obs)
    emit = np.empty((n, 2))
    for t, o in enumerate(obs):
        if o:
            emit[t, 0], emit[t, 1] = guess, 1.0 - slip
        else:
            emit[t, 0], emit[t, 1] = 1.0 - guess, slip

    alpha = np.zeros((n, 2))
    scale = np.zeros(n)

    alpha[0, 0] = (1.0 - prior) * emit[0, 0]
    alpha[0, 1] = prior * emit[0, 1]
    scale[0] = alpha[0].sum()
    if scale[0] <= 0:
        return None, None, -np.inf
    alpha[0] /= scale[0]

    for t in range(1, n):
        alpha[t, 0] = alpha[t - 1, 0] * (1.0 - learn) * emit[t, 0]
        alpha[t, 1] = (alpha[t - 1, 0] * learn + alpha[t - 1, 1]) * emit[t, 1]
        scale[t] = alpha[t].sum()
        if scale[t] <= 0:
            return None, None, -np.inf
        alpha[t] /= scale[t]

    beta = np.zeros((n, 2))
    beta[n - 1] = 1.0
    for t in range(n - 2, -1, -1):
        beta[t, 0] = ((1.0 - learn) * emit[t + 1, 0] * beta[t + 1, 0]
                      + learn * emit[t + 1, 1] * beta[t + 1, 1]) / scale[t + 1]
        beta[t, 1] = (emit[t + 1, 1] * beta[t + 1, 1]) / scale[t + 1]

    gamma = alpha * beta
    gsum = gamma.sum(axis=1, keepdims=True)
    gsum[gsum == 0] = 1.0
    gamma /= gsum

    xi_01 = np.zeros(max(0, n - 1))
    for t in range(n - 1):
        xi_01[t] = (alpha[t, 0] * learn * emit[t + 1, 1] * beta[t + 1, 1]) / scale[t + 1]

    return gamma, xi_01, float(np.log(scale).sum())


def _run_em(seqs, start, max_iterations, tolerance, max_guess, max_slip):
    prior = _clamp(start["prior"], _EPS, 1 - _EPS)
    learn = _clamp(start["learn"], _EPS, 1 - _EPS)
    guess = _clamp(start["guess"], _EPS, max_guess)
    slip = _clamp(start["slip"], _EPS, max_slip)

    prev_ll = -np.inf
    converged = False
    iterations = 0

    for iterations in range(1, max_iterations + 1):
        prior_num = 0.0
        learn_num = learn_den = 0.0
        guess_num = guess_den = 0.0
        slip_num = slip_den = 0.0
        total_ll = 0.0
        used = 0

        for obs in seqs:
            gamma, xi_01, ll = _forward_backward(obs, prior, learn, guess, slip)
            if gamma is None or not math.isfinite(ll):
                continue
            used += 1
            total_ll += ll
            prior_num += gamma[0, 1]

            if len(obs) > 1:
                learn_num += xi_01.sum()
                learn_den += gamma[:-1, 0].sum()

            obs_arr = np.asarray(obs, dtype=float)
            guess_num += float((gamma[:, 0] * obs_arr).sum())
            guess_den += float(gamma[:, 0].sum())
            slip_num += float((gamma[:, 1] * (1.0 - obs_arr)).sum())
            slip_den += float(gamma[:, 1].sum())

        if used == 0:
            return None

        prior = _clamp(prior_num / used, _EPS, 1 - _EPS)
        if learn_den > 0:
            learn = _clamp(learn_num / learn_den, _EPS, 1 - _EPS)
        if guess_den > 0:
            guess = _clamp(guess_num / guess_den, _EPS, max_guess)
        if slip_den > 0:
            slip = _clamp(slip_num / slip_den, _EPS, max_slip)

        if abs(total_ll - prev_ll) < tolerance:
            prev_ll = total_ll
            converged = True
            break
        prev_ll = total_ll

    return prior, learn, guess, slip, float(prev_ll), iterations, converged


def fit_bkt(sequences, max_iterations=200, tolerance=1e-6, init=None,
            max_guess=DEFAULT_MAX_GUESS, max_slip=DEFAULT_MAX_SLIP,
            restarts=DEFAULT_RESTARTS, seed=42):
    """Fit BKT parameters from response sequences by expectation-maximisation.

    sequences : iterable of sequences of truthy/falsy responses, one per learner
    init      : optional starting values; when given it is used as the first
                restart and the rest are randomised
    restarts  : number of randomised EM restarts; the best non-degenerate
                solution by log-likelihood is returned

    Returns a BKTFitResult (check `.degenerate` before trusting it), or None if
    there is no usable data.
    """
    seqs = [[1 if o else 0 for o in s] for s in sequences if len(s) > 0]
    if not seqs:
        return None

    rng = random.Random(seed)
    starts = [dict(init) if init else {"prior": 0.3, "learn": 0.2,
                                       "guess": 0.2, "slip": 0.1}]
    for _ in range(max(0, restarts - 1)):
        starts.append({
            "prior": rng.uniform(0.05, 0.70),
            "learn": rng.uniform(0.02, 0.50),
            "guess": rng.uniform(0.05, max_guess * 0.9),
            "slip": rng.uniform(0.02, max_slip * 0.9),
        })

    best = None
    best_sound = None
    for start in starts:
        outcome = _run_em(seqs, start, max_iterations, tolerance, max_guess, max_slip)
        if outcome is None:
            continue
        prior, learn, guess, slip, ll, iterations, converged = outcome
        reasons = degeneracy_reasons(prior, learn, guess, slip, max_guess, max_slip)
        candidate = BKTFitResult(
            prior=float(prior), learn=float(learn), guess=float(guess), slip=float(slip),
            log_likelihood=ll, iterations=iterations, converged=converged,
            n_sequences=len(seqs), n_responses=int(sum(len(s) for s in seqs)),
            degenerate=bool(reasons), degeneracy_reasons=reasons, restarts=len(starts),
        )
        if best is None or candidate.log_likelihood > best.log_likelihood:
            best = candidate
        if not reasons and (best_sound is None
                            or candidate.log_likelihood > best_sound.log_likelihood):
            best_sound = candidate

    return best_sound or best


def fit_bkt_by_skill(records, min_responses=20, skip_degenerate=True, **kwargs):
    """Fit one parameter set per skill.

    records          : iterable of (user_id, skill, correct)
    min_responses    : skills with less data than this are not fitted, because
                       four parameters are not identifiable from a handful of
                       responses
    skip_degenerate  : omit skills whose best fit rests on a constraint
                       boundary, so the caller falls back to configured
                       defaults instead of deploying an unidentified parameter

    Returns (fitted, rejected) where `rejected` maps skill -> reason.
    """
    grouped = {}
    for user_id, skill, correct in records:
        grouped.setdefault(skill, {}).setdefault(user_id, []).append(1 if correct else 0)

    fitted, rejected = {}, {}
    for skill, by_user in grouped.items():
        sequences = list(by_user.values())
        n = sum(len(s) for s in sequences)
        if n < min_responses:
            rejected[skill] = f"only {n} responses (minimum {min_responses})"
            continue
        result = fit_bkt(sequences, **kwargs)
        if result is None:
            rejected[skill] = "no usable sequences"
            continue
        if skip_degenerate and result.degenerate:
            rejected[skill] = "degenerate fit: " + "; ".join(result.degeneracy_reasons)
            continue
        fitted[skill] = result
    return fitted, rejected
