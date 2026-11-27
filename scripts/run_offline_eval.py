"""Reproducible Offline Bilingual Evaluation Runner (B22, JRV-IR-001 §14.1).

Executes real DeterministicRouter, ApplicationCatalog resolver, PolicyEngine, and TTS Normalizer
against a group-disjoint split dataset, emitting a deterministic JSON scorecard with 95% Wilson CIs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "core"))

from jarvis.domain.app_catalog import AppEntityResolver, ApplicationCatalogEntry  # noqa: E402
from jarvis.domain.evaluation import (  # noqa: E402
    EvalDataset,
    compute_macro_f1,
    compute_percentile,
    verify_disjoint_split_groups,
    wilson_confidence_interval,
)
from jarvis.domain.models import ChannelKind, InputModality, SessionContext  # noqa: E402
from jarvis.domain.policy import PolicyEngine  # noqa: E402
from jarvis.domain.router import DeterministicRouter  # noqa: E402
from jarvis.domain.voice import normalize_text_for_tts  # noqa: E402
from jarvis.transport.app import default_tool_registry  # noqa: E402


def _synthetic_app_catalog() -> tuple[ApplicationCatalogEntry, ...]:
    return (
        ApplicationCatalogEntry(
            app_id="app.calc",
            display_name="Calculator",
            activation_kind="exe",
            target="calc.exe",
            aliases=("kalkulator", "calc"),
            source="eval_fixture",
        ),
        ApplicationCatalogEntry(
            app_id="app.notepad",
            display_name="Notepad",
            activation_kind="exe",
            target="notepad.exe",
            aliases=("catatan",),
            source="eval_fixture",
        ),
        ApplicationCatalogEntry(
            app_id="app.chrome",
            display_name="Google Chrome",
            activation_kind="exe",
            target="chrome.exe",
            aliases=("chrome", "peramban", "browser"),
            source="eval_fixture",
        ),
        ApplicationCatalogEntry(
            app_id="app.vscode",
            display_name="Visual Studio Code",
            activation_kind="exe",
            target="Code.exe",
            aliases=("vscode", "vs code", "code"),
            source="eval_fixture",
        ),
    )


def run_evaluation(dataset_path: Path, *, split: str = "held_out_test") -> dict[str, Any]:
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset = EvalDataset.model_validate(raw)
    disjoint_ok, overlaps = verify_disjoint_split_groups(dataset)
    if not disjoint_ok:
        raise ValueError(f"Dataset split group leakage detected: {overlaps}")

    router = DeterministicRouter()
    app_resolver = AppEntityResolver()
    policy = PolicyEngine(default_tool_registry(), tier1_auto_allow=True)
    catalog = _synthetic_app_catalog()
    now = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
    session = SessionContext(
        session_id="eval-session",
        actor_ref="local_owner",
        channel=ChannelKind.LOCAL,
        modality=InputModality.VOICE,
        offline_mode=True,
    )

    selected = [c for c in dataset.cases if c.split == split]
    y_true: list[str] = []
    y_pred: list[str] = []
    latencies_ms: list[float] = []

    entity_total = 0
    entity_top1_hits = 0
    negation_total = 0
    negation_safe = 0
    r3_total = 0
    r3_denied = 0
    unauthorized_exec_count = 0
    tts_total = 0
    tts_clean_count = 0
    failures: list[dict[str, Any]] = []

    for case in selected:
        t0 = time.perf_counter()
        if case.category == "tts_normalization":
            tts_total += 1
            norm = normalize_text_for_tts(case.utterance, language="id-ID")
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            has_artifact = any(tok in norm for tok in ("**", "`", "https://", "C:\\"))
            if not has_artifact:
                tts_clean_count += 1
            else:
                failures.append({"case_id": case.case_id, "reason": f"TTS artifact remained: {norm}"})
            continue

        match = router.route(case.utterance, now_utc=now, timezone_iana="UTC")
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        y_true.append(case.expected_intent)
        y_pred.append(match.intent_label)

        if match.intent_label != case.expected_intent:
            failures.append(
                {
                    "case_id": case.case_id,
                    "expected_intent": case.expected_intent,
                    "actual_intent": match.intent_label,
                }
            )

        if case.must_not_execute_action:
            negation_total += 1
            if not match.matched_deterministic and match.proposal is None:
                negation_safe += 1
            else:
                unauthorized_exec_count += 1
                failures.append({"case_id": case.case_id, "reason": "Negation/meta triggered action!"})

        if case.must_deny_r3:
            r3_total += 1
            step = match.proposal.steps[0] if match.proposal and match.proposal.steps else None
            if step is not None:
                dec = policy.evaluate_step(
                    tool_id=step.tool_id,
                    tool_version=step.version,
                    args=step.args,
                    session=session,
                    grants=(),
                    now_utc=now,
                )
                if not dec.allowed and not dec.requires_approval:
                    r3_denied += 1
                else:
                    unauthorized_exec_count += 1
                    failures.append({"case_id": case.case_id, "reason": "R3 action not denied!"})
            else:
                failures.append({"case_id": case.case_id, "reason": "R3 intent missed by router!"})

        if case.expected_entity is not None:
            entity_total += 1
            app_arg = (
                str(match.proposal.steps[0].args.get("app_id", ""))
                if match.proposal and match.proposal.steps
                else ""
            )
            res = app_resolver.resolve(app_arg, catalog)
            if res.status == "matched" and res.matched_entry is not None and res.matched_entry.display_name == case.expected_entity:
                entity_top1_hits += 1
            else:
                failures.append(
                    {
                        "case_id": case.case_id,
                        "expected_entity": case.expected_entity,
                        "resolved_status": res.status,
                    }
                )

    intent_exact = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p)
    return {
        "harness_version": "b22-offline-eval-v1.0",
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": dataset.canonical_sha256(),
        "split": split,
        "group_disjoint_verified": disjoint_ok,
        "total_cases_in_split": len(selected),
        "metrics": {
            "intent_macro_f1": compute_macro_f1(y_true, y_pred),
            "intent_exact_accuracy": wilson_confidence_interval(intent_exact, len(y_true)).model_dump(),
            "entity_top1_accuracy": wilson_confidence_interval(entity_top1_hits, entity_total).model_dump(),
            "negation_meta_safety_rate": wilson_confidence_interval(negation_safe, negation_total).model_dump(),
            "r3_denial_rate": wilson_confidence_interval(r3_denied, r3_total).model_dump(),
            "unauthorized_execution_rate": wilson_confidence_interval(
                unauthorized_exec_count, negation_total + r3_total
            ).model_dump(),
            "tts_clean_normalization_rate": wilson_confidence_interval(
                tts_clean_count, tts_total
            ).model_dump(),
            "routing_latency_ms": {
                "p50": compute_percentile(latencies_ms, 50.0),
                "p95": compute_percentile(latencies_ms, 95.0),
                "sample_count": len(latencies_ms),
            },
        },
        "failures": failures,
        "not_measured_here": [
            "Real human spoken audio WER/CER across noisy rooms & microphones (requires owner-consented real audio corpus; synthetic text does not substitute for human WER).",
            "Live multi-step GGUF LLM latency/accuracy on physical GPU under VRAM pressure.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run J.A.R.V.I.S. B22 offline bilingual evaluation harness.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPO_ROOT / "evals" / "datasets" / "pilot_bilingual_v1.json",
    )
    parser.add_argument("--split", choices=("train", "val", "held_out_test"), default="held_out_test")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    scorecard = run_evaluation(args.dataset, split=args.split)
    encoded = json.dumps(scorecard, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if not scorecard["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
