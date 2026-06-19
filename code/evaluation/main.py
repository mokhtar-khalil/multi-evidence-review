from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import time
from collections import Counter
from pathlib import Path

AGENT_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("evidence_agent_main", AGENT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load agent module at {AGENT_PATH}")
AGENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT)
OUTPUT_COLUMNS = AGENT.OUTPUT_COLUMNS
run = AGENT.run


TARGET_COLUMNS = [
    "evidence_standard_met",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "supporting_image_ids",
    "valid_image",
    "severity",
]
DISCORD_STYLE_COLUMNS = [
    "claim_object",
    "valid_image",
    "object_part",
    "evidence_standard_met",
    "claim_status",
    "supporting_image_ids",
    "severity",
    "risk_flags",
    "issue_type",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def score(gold: list[dict[str, str]], pred: list[dict[str, str]]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for col in TARGET_COLUMNS:
        correct = sum(1 for g, p in zip(gold, pred) if g[col] == p[col])
        metrics[f"{col}_accuracy"] = correct / max(1, len(gold))
    exact = sum(1 for g, p in zip(gold, pred) if all(g[col] == p[col] for col in TARGET_COLUMNS))
    metrics["exact_structured_accuracy"] = exact / max(1, len(gold))
    field_scores = [
        sum(1 for g, p in zip(gold, pred) if g[col] == p[col]) / max(1, len(gold))
        for col in DISCORD_STYLE_COLUMNS
    ]
    metrics["mean_field_accuracy"] = sum(field_scores) / max(1, len(field_scores))
    return metrics


def write_report(
    report_path: Path,
    metrics: dict[str, float],
    runtime: float,
    sample_rows: int,
    sample_images: int,
    test_rows: int,
    test_images: int,
    model: str,
    vlm_enabled: bool,
) -> None:
    calls_sample = sample_rows if vlm_enabled else 0
    calls_test = test_rows if vlm_enabled else 0
    approx_input_tokens = (sample_rows + test_rows) * 900
    approx_output_tokens = (sample_rows + test_rows) * 180
    report = f"""# Evaluation Report

## Strategy Comparison

Two strategies are supported by the code:

1. `vlm_structured_json`: one multimodal model call per claim, with all submitted images, the claim conversation, user history, and evidence requirements in a strict JSON prompt. This is the final intended strategy when `OPENAI_API_KEY` is available.
2. `deterministic_fallback`: local CSV/image validation, conversation parsing, user-history risk rules, prompt-injection flagging, and conservative defaults. This keeps the pipeline runnable without secrets but is not expected to match full visual judgment.

Current evaluation mode: `{"vlm_structured_json" if vlm_enabled else "deterministic_fallback"}` using model `{model}`.

## Sample Metrics

"""
    for key, value in metrics.items():
        report += f"- {key}: {value:.3f}\n"
    report += f"""
## Operational Analysis

- Sample rows processed: {sample_rows}
- Test rows expected: {test_rows}
- Sample images processed: {sample_images}
- Test images expected: {test_images}
- Approximate model calls for sample processing: {calls_sample}
- Approximate model calls for full test processing: {calls_test}
- Approximate token usage for sample plus test: {approx_input_tokens:,} input tokens and {approx_output_tokens:,} output tokens, excluding image-token accounting.
- Cost assumption: with a low-cost vision model, one call per claim, and resized images, expect roughly a low single-digit dollar cost for this corpus; exact cost depends on the chosen provider/model image-token pricing.
- Runtime observed for this evaluation run: {runtime:.1f} seconds.
- Latency and rate limits: the agent processes one claim per call, caches responses under `code/.cache/`, retries transient API failures with exponential backoff, and can be throttled externally if provider RPM/TPM limits are tight.
- Batching: not used for final decisions because each row has different image sets and should get independent JSON validation. CSV loading and local validation are batched in-process.

## Final Strategy

Use `python code/main.py --input dataset/claims.csv --output output.csv` with `OPENAI_API_KEY` set for the final VLM path. If no key is available, the command still emits schema-valid conservative predictions using the deterministic fallback.
"""
    report_path.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate on sample_claims.csv")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[2], type=Path)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--no-vlm", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    out_path = repo_root / "code" / "evaluation" / "sample_predictions.csv"

    start = time.time()
    pred = run(
        input_csv=repo_root / "dataset" / "sample_claims.csv",
        output_csv=out_path,
        repo_root=repo_root,
        model=args.model,
        use_vlm=not args.no_vlm,
    )
    runtime = time.time() - start

    gold = read_csv(repo_root / "dataset" / "sample_claims.csv")
    metrics = score(gold, pred)
    sample_images = sum(len(r["image_paths"].split(";")) for r in gold)
    test = read_csv(repo_root / "dataset" / "claims.csv")
    test_images = sum(len(r["image_paths"].split(";")) for r in test)
    write_report(
        repo_root / "code" / "evaluation" / "evaluation_report.md",
        metrics,
        runtime,
        len(gold),
        sample_images,
        len(test),
        test_images,
        args.model,
        not args.no_vlm,
    )
    print("Wrote", out_path)
    print("Columns:", ",".join(OUTPUT_COLUMNS))
    for key, value in metrics.items():
        print(f"{key}: {value:.3f}")
    print("Prediction distribution:", Counter(r["claim_status"] for r in pred))


if __name__ == "__main__":
    main()
