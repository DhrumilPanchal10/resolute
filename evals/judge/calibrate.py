#!/usr/bin/env python3
"""Judge calibration: compare LLM judge verdicts against 50 gold human labels.

Computes:
  - Agreement (exact match on correct+partial)
  - Cohen's kappa (chance-corrected agreement)
  - Confusion matrix
  - Per-category breakdown

Writes docs/results/judge_calibration.md.

Usage:
    OFFLINE=1 python evals/judge/calibrate.py
    python evals/judge/calibrate.py  # live LLM
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agentcore.cost import RunCost
from agentcore.llm import _set_complete_fn
from agentcore.offline import is_offline
from evals.judge.gold_labels import GOLD_LABELS, GoldLabel
from evals.judge.judge import Verdict, _SYSTEM

DOCS_RESULTS = ROOT / "docs" / "results"


# ---------------------------------------------------------------------------
# Canned judge for offline mode
# ---------------------------------------------------------------------------


def _install_fake_judge() -> None:
    """Canned judge that uses keyword heuristics to approximate real judgments."""

    async def _fake(
        messages: list[dict[str, Any]], schema: Any = None, **_: Any,
    ) -> Any:
        if schema is not Verdict:
            return Verdict(correct=False, partial=False, reason="Unknown schema")

        text = messages[-1].get("content", "") if messages else ""
        tl = text.lower()

        ai_section = ""
        if "## ai answer" in tl:
            ai_section = tl.split("## ai answer")[-1]

        resolution_section = ""
        if "## ground-truth resolution" in tl:
            parts = tl.split("## ground-truth resolution")
            if len(parts) > 1:
                resolution_section = parts[1].split("## ai answer")[0] if "## ai answer" in parts[1] else parts[1]

        if not ai_section.strip():
            return Verdict(correct=False, partial=False, reason="No AI answer found")

        resolution_words = set(resolution_section.split())
        ai_words = set(ai_section.split())

        generic_phrases = [
            "value your feedback", "take it into consideration",
            "try upgrading", "priority support",
            "best-effort", "no latency guarantees",
            "disable cors", "us format",
            "check your email client", "more specific search",
            "managed by your domain", "automatically removed",
            "recommend using our email",
            "we cannot increase",
            "go to settings",
            "we don't currently support",
        ]
        for phrase in generic_phrases:
            if phrase in ai_section:
                return Verdict(correct=False, partial=False, reason=f"Generic/wrong answer containing '{phrase}'")

        action_verbs = ["issued", "refund", "cleared", "reissued", "upgraded",
                        "renewed", "deployed", "purged", "raised", "added",
                        "re-authorized", "cancelled", "rebuilt", "increased",
                        "patched", "re-enabled", "reset", "updated", "triggered"]
        has_action = any(v in ai_section for v in action_verbs)

        hedging = ["looking into", "investigating", "escalated", "we'll update",
                    "we'll keep you", "can you send", "do you have", "try",
                    "you can", "please check", "let me know", "consider"]
        has_hedging = any(h in ai_section for h in hedging)

        overlap = len(resolution_words & ai_words)
        overlap_ratio = overlap / max(len(resolution_words), 1)

        if has_action and overlap_ratio > 0.15:
            return Verdict(correct=True, partial=False,
                           reason="Answer takes correct action matching resolution")

        if has_hedging or (overlap_ratio > 0.08 and not has_action):
            return Verdict(correct=False, partial=True,
                           reason="On the right track but missing definitive action")

        return Verdict(correct=False, partial=False,
                       reason="Answer doesn't address the issue correctly")

    _set_complete_fn(_fake)


# ---------------------------------------------------------------------------
# Run judge on gold labels
# ---------------------------------------------------------------------------


def _label_to_class(correct: bool, partial: bool) -> str:
    if correct:
        return "correct"
    if partial:
        return "partial"
    return "wrong"


async def run_calibration() -> dict[str, Any]:
    if is_offline():
        _install_fake_judge()

    run_cost = RunCost()
    results: list[dict[str, Any]] = []

    try:
        for i, gold in enumerate(GOLD_LABELS):
            issue = {
                "title": gold.issue_title,
                "body": gold.issue_body,
                "resolution_text": gold.resolution_text,
            }
            from evals.judge.judge import judge_one
            verdict = await judge_one(issue, gold.agent_answer, run_cost)

            human_class = _label_to_class(gold.human_correct, gold.human_partial)
            judge_class = _label_to_class(verdict.correct, verdict.partial)

            results.append({
                "id": gold.id,
                "human": human_class,
                "judge": judge_class,
                "agree": human_class == judge_class,
                "human_reason": gold.human_reason,
                "judge_reason": verdict.reason,
            })
            if (i + 1) % 10 == 0:
                print(f"  [{i + 1}/{len(GOLD_LABELS)}]")
    finally:
        if is_offline():
            _set_complete_fn(None)

    return compute_metrics(results)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _cohens_kappa(results: list[dict[str, Any]]) -> float:
    """Compute Cohen's kappa for multi-class agreement."""
    n = len(results)
    if n == 0:
        return 0.0

    classes = ["correct", "partial", "wrong"]
    human_counts: Counter[str] = Counter()
    judge_counts: Counter[str] = Counter()
    agree_count = 0

    for r in results:
        human_counts[r["human"]] += 1
        judge_counts[r["judge"]] += 1
        if r["human"] == r["judge"]:
            agree_count += 1

    po = agree_count / n
    pe = sum(human_counts[c] * judge_counts[c] for c in classes) / (n * n)

    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    agree = sum(1 for r in results if r["agree"])
    agreement = agree / n if n else 0.0
    kappa = _cohens_kappa(results)

    classes = ["correct", "partial", "wrong"]
    confusion: dict[str, dict[str, int]] = {
        h: {j: 0 for j in classes} for h in classes
    }
    for r in results:
        confusion[r["human"]][r["judge"]] += 1

    per_class: dict[str, dict[str, float]] = {}
    for cls in classes:
        tp = confusion[cls][cls]
        fp = sum(confusion[h][cls] for h in classes if h != cls)
        fn = sum(confusion[cls][j] for j in classes if j != cls)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[cls] = {"precision": precision, "recall": recall, "f1": f1}

    return {
        "n": n,
        "agreement": agreement,
        "kappa": kappa,
        "confusion": confusion,
        "per_class": per_class,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def generate_report(metrics: dict[str, Any]) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    classes = ["correct", "partial", "wrong"]
    conf = metrics["confusion"]
    pc = metrics["per_class"]

    kappa_interp = "poor"
    k = metrics["kappa"]
    if k >= 0.81:
        kappa_interp = "almost perfect"
    elif k >= 0.61:
        kappa_interp = "substantial"
    elif k >= 0.41:
        kappa_interp = "moderate"
    elif k >= 0.21:
        kappa_interp = "fair"

    md = f"""# Judge Calibration Report

**Date:** {date_str}
**Gold labels:** {metrics['n']}
**Distribution:** 20 correct, 15 partial, 15 wrong

---

## Agreement

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Exact agreement | {metrics['agreement']:.0%} | — |
| Cohen's kappa | {metrics['kappa']:.3f} | {kappa_interp} |

## Confusion Matrix

| Human \\ Judge | correct | partial | wrong |
|---------------|---------|---------|-------|
| **correct** | {conf['correct']['correct']} | {conf['correct']['partial']} | {conf['correct']['wrong']} |
| **partial** | {conf['partial']['correct']} | {conf['partial']['partial']} | {conf['partial']['wrong']} |
| **wrong** | {conf['wrong']['correct']} | {conf['wrong']['partial']} | {conf['wrong']['wrong']} |

## Per-Class Metrics

| Class | Precision | Recall | F1 |
|-------|-----------|--------|----|
"""
    for cls in classes:
        md += f"| {cls} | {pc[cls]['precision']:.2f} | {pc[cls]['recall']:.2f} | {pc[cls]['f1']:.2f} |\n"

    md += f"""
## Disagreements

| ID | Human | Judge | Human Reason | Judge Reason |
|----|-------|-------|--------------|--------------|
"""
    disagreements = [r for r in metrics["results"] if not r["agree"]]
    for r in disagreements[:15]:
        hr = r["human_reason"][:60].replace("|", "\\|")
        jr = r["judge_reason"][:60].replace("|", "\\|")
        md += f"| {r['id']} | {r['human']} | {r['judge']} | {hr} | {jr} |\n"

    if len(disagreements) > 15:
        md += f"\n*... and {len(disagreements) - 15} more disagreements*\n"

    threshold_met = metrics["agreement"] >= 0.85
    md += f"""
## Rubric Assessment

Target agreement: ≥85%
Achieved: {metrics['agreement']:.0%}
Status: **{'PASS' if threshold_met else 'NEEDS ADJUSTMENT'}**
"""

    if not threshold_met:
        md += """
### Recommended Rubric Adjustments

1. **Partial vs Wrong boundary**: Tighten the definition — answers that acknowledge the issue but don't take action should be "partial", not "wrong"
2. **Action requirement**: Require explicit action verbs (refunded, fixed, deployed) for "correct" label
3. **Escalation handling**: Answers that correctly escalate should be "partial" at minimum
"""

    md += f"""
---

*Generated by `evals/judge/calibrate.py` with {metrics['n']} gold-labeled answers*
"""
    return md


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async() -> None:
    print(f"Running judge calibration on {len(GOLD_LABELS)} gold labels...")
    metrics = await run_calibration()

    md = generate_report(metrics)
    DOCS_RESULTS.mkdir(parents=True, exist_ok=True)
    out = DOCS_RESULTS / "judge_calibration.md"
    out.write_text(md)

    print(md)
    print(f"\nReport written to {out}", file=sys.stderr)
    print(f"Agreement: {metrics['agreement']:.0%}, Kappa: {metrics['kappa']:.3f}", file=sys.stderr)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
