# Multi-Modal Evidence Review Agent

This solution reads the provided CSV files and local images, then writes an `output.csv`
using the exact schema from `problem_statement.md`.

## Run Final Predictions

From the repository root:

```powershell
python code/main.py --input dataset/claims.csv --output output.csv
```

For the intended multimodal path, set `OPENAI_API_KEY` first or put it in a
`.env` file at the repository root. The default model can be overridden with
`OPENAI_VISION_MODEL` or `--model`.

```powershell
$env:OPENAI_API_KEY="..."
python code/main.py --input dataset/claims.csv --output output.csv --model gpt-4.1-mini
```

If no API key is present, the program still produces schema-valid conservative
predictions with a deterministic fallback that parses the claim conversation, checks
image existence/basic quality, applies user-history risk, and flags prompt-injection
language.

## Final Recommended Mode

The strongest local sample results came from the single calibrated API agent:

```powershell
python code/main.py --input dataset/claims.csv --output output.csv --model gpt-4.1-mini
```

This is one VLM-based evidence-review agent plus deterministic insurance-style
calibration for schema consistency, severity, risk flags, issue taxonomy, and
supporting image IDs. The rule layer is general and uses object/issue/status
logic rather than file-specific answers.

## Evaluate

```powershell
python code/evaluation/main.py
```

This writes:

- `code/evaluation/sample_predictions.csv`
- `code/evaluation/evaluation_report.md`

Use `--no-vlm` to force the deterministic fallback during evaluation.

## Approach

The primary path sends one structured multimodal prompt per claim containing:

- all submitted images, labeled by image ID
- the claim conversation
- the matched user-history row
- the evidence requirements table
- allowed output values and schema constraints

The model returns strict JSON, which is normalized and validated before CSV writing.
History is only merged into `risk_flags`; it does not override visual evidence.

Responses are cached in `code/.cache/` to avoid repeated model calls while iterating.
