"""Pure-Domain Offline Bilingual Evaluation Metrics, Statistical CIs & Leakage Guards (B22, NFR-07, NFR-08, NFR-16).

Strictly OS-independent: computes deterministic WER/CER, Intent Macro-F1, 95% Wilson Score intervals,
seeded Paired Bootstrap difference CIs, group-disjoint split validation, and reproducible scorecards.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from jarvis.domain.models import StrictModel

_NORM_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_eval_text(text: str) -> str:
    """Documented deterministic text normalization for WER/CER (lowercase, strip punctuation, collapse spaces)."""
    cleaned = _NORM_PUNCT_RE.sub(" ", text.casefold())
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _levenshtein(seq_a: list[str], seq_b: list[str]) -> int:
    m, n = len(seq_a), len(seq_b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        ai = seq_a[i - 1]
        for j in range(1, n + 1):
            cost = 0 if ai == seq_b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def compute_wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate under documented normalization."""
    ref_words = normalize_eval_text(reference).split()
    hyp_words = normalize_eval_text(hypothesis).split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return _levenshtein(ref_words, hyp_words) / len(ref_words)


def compute_cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate under documented normalization."""
    ref_chars = list(normalize_eval_text(reference))
    hyp_chars = list(normalize_eval_text(hypothesis))
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    return _levenshtein(ref_chars, hyp_chars) / len(ref_chars)


class ProportionWithWilsonCI(StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float = Field(ge=0.0, le=1.0)
    ci95_low: float = Field(ge=0.0, le=1.0)
    ci95_high: float = Field(ge=0.0, le=1.0)


def wilson_confidence_interval(
    successes: int, total: int, *, z: float = 1.959963984540054
) -> ProportionWithWilsonCI:
    """Compute exact 95% Wilson score confidence interval for binomial proportions (JRV-IR-001 §14.1)."""
    if total <= 0:
        return ProportionWithWilsonCI(numerator=0, denominator=0, rate=0.0, ci95_low=0.0, ci95_high=0.0)
    s = max(0, min(successes, total))
    p = s / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    half = (z / denom) * math.sqrt((p * (1.0 - p) / total) + (z2 / (4.0 * total * total)))
    return ProportionWithWilsonCI(
        numerator=s,
        denominator=total,
        rate=round(p, 6),
        ci95_low=round(max(0.0, center - half), 6),
        ci95_high=round(min(1.0, center + half), 6),
    )


@dataclass(frozen=True)
class BootstrapDiffResult:
    mean_diff: float
    ci95_low: float
    ci95_high: float
    n_pairs: int
    n_resamples: int
    seed: int


def paired_bootstrap_ci(
    baseline: list[float],
    candidate: list[float],
    *,
    n_resamples: int = 1000,
    seed: int = 42,
) -> BootstrapDiffResult:
    """Deterministic paired bootstrap 95% CI for (candidate - baseline) differences (§14.1)."""
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("Paired bootstrap requires non-empty equal-length sequences.")
    n = len(baseline)
    diffs = [c - b for b, c in zip(baseline, candidate, strict=True)]
    rng = random.Random(seed)  # noqa: S311
    means: list[float] = []
    for _ in range(n_resamples):
        sample_sum = sum(diffs[rng.randrange(n)] for _ in range(n))
        means.append(sample_sum / n)
    means.sort()
    lo_idx = max(0, int(0.025 * n_resamples))
    hi_idx = min(n_resamples - 1, int(0.975 * n_resamples))
    return BootstrapDiffResult(
        mean_diff=round(sum(diffs) / n, 6),
        ci95_low=round(means[lo_idx], 6),
        ci95_high=round(means[hi_idx], 6),
        n_pairs=n,
        n_resamples=n_resamples,
        seed=seed,
    )


def compute_macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    """Compute unweighted Macro-F1 across all gold intent labels."""
    if len(y_true) != len(y_pred) or not y_true:
        return 0.0
    labels = sorted(set(y_true))
    f1s: list[float] = []
    for lbl in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == lbl and p == lbl)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != lbl and p == lbl)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == lbl and p != lbl)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2.0 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        f1s.append(f1)
    return round(sum(f1s) / len(f1s), 6)


def compute_percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return round(ordered[idx], 4)


EvalSplit = Literal["train", "val", "held_out_test"]
EvalCategory = Literal[
    "app_launch",
    "negation_or_meta",
    "volume",
    "time",
    "file_search",
    "memory_reminder",
    "compound_multi_step",
    "prohibited_r3",
    "tts_normalization",
]


class EvalCase(StrictModel):
    case_id: str = Field(min_length=2, max_length=64)
    split: EvalSplit
    group_id: str = Field(min_length=2, max_length=64)
    language: Literal["id", "en", "mixed"]
    category: EvalCategory
    utterance: str = Field(min_length=1, max_length=1000)
    expected_intent: str = Field(min_length=1, max_length=64)
    expected_tool_id: str | None = None
    expected_entity: str | None = None
    must_not_execute_action: bool = False
    must_deny_r3: bool = False


class EvalDataset(StrictModel):
    dataset_version: str
    description: str
    cases: tuple[EvalCase, ...]

    def canonical_sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


def verify_disjoint_split_groups(dataset: EvalDataset) -> tuple[bool, list[str]]:
    """Enforce group-disjoint splitting across train / val / held_out_test to prevent paraphrase leakage (§14.1)."""
    groups_by_split: dict[str, set[str]] = {"train": set(), "val": set(), "held_out_test": set()}
    for c in dataset.cases:
        groups_by_split[c.split].add(c.group_id)
    overlaps: list[str] = []
    pairs = (("train", "val"), ("train", "held_out_test"), ("val", "held_out_test"))
    for a, b in pairs:
        shared = sorted(groups_by_split[a] & groups_by_split[b])
        if shared:
            overlaps.append(f"{a}<->{b}: {', '.join(shared)}")
    return (len(overlaps) == 0, overlaps)
