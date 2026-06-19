# Evaluation Report

## Strategy Comparison

Two strategies are supported by the code:

1. `vlm_structured_json`: one multimodal model call per claim, with all submitted images, the claim conversation, user history, and evidence requirements in a strict JSON prompt. This is the final intended strategy when `OPENAI_API_KEY` is available.
2. `deterministic_fallback`: local CSV/image validation, conversation parsing, user-history risk rules, prompt-injection flagging, and conservative defaults. This keeps the pipeline runnable without secrets but is not expected to match full visual judgment.

Current evaluation mode: `deterministic_fallback` using model `gpt-4.1-mini`.

## Sample Metrics

- evidence_standard_met_accuracy: 0.850
- risk_flags_accuracy: 0.450
- issue_type_accuracy: 0.500
- object_part_accuracy: 0.650
- claim_status_accuracy: 0.650
- supporting_image_ids_accuracy: 0.700
- valid_image_accuracy: 0.900
- severity_accuracy: 0.600
- exact_structured_accuracy: 0.300
- mean_field_accuracy: 0.700

## Operational Analysis

- Sample rows processed: 20
- Test rows expected: 44
- Sample images processed: 29
- Test images expected: 82
- Approximate model calls for sample processing: 0
- Approximate model calls for full test processing: 0
- Approximate token usage for sample plus test: 57,600 input tokens and 11,520 output tokens, excluding image-token accounting.
- Cost assumption: with a low-cost vision model, one call per claim, and resized images, expect roughly a low single-digit dollar cost for this corpus; exact cost depends on the chosen provider/model image-token pricing.
- Runtime observed for this evaluation run: 0.4 seconds.
- Latency and rate limits: the agent processes one claim per call, caches responses under `code/.cache/`, retries transient API failures with exponential backoff, and can be throttled externally if provider RPM/TPM limits are tight.
- Batching: not used for final decisions because each row has different image sets and should get independent JSON validation. CSV loading and local validation are batched in-process.

## Final Strategy

Use `python code/main.py --input dataset/claims.csv --output output.csv` with `OPENAI_API_KEY` set for the final VLM path. If no key is available, the command still emits schema-valid conservative predictions using the deterministic fallback.
