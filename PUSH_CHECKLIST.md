# Push Checklist

Use this checklist before pushing the repository.

## Keep

- `code/`
- `dataset/`
- `output.csv`
- `code.zip`
- `solution_walkthrough.ipynb`
- `problem_statement.md`
- `README.md`
- `AGENTS.md`
- `.gitignore`
- `.env.example`

## Do Not Push

These are ignored by `.gitignore`:

- `.env`
- `log.txt`
- `analysis_sheets/`
- `artifacts/generated/`
- `code/.cache/`
- scratch CSVs such as `compare_*.csv`, `output_smoke.csv`, `sample_api_predictions.csv`
- downloaded archives such as `repo.zip` and `repo_full.zip`

## Final Submission Files

For HackerRank upload, use:

- `code.zip`
- `output.csv`
- `%USERPROFILE%/hackerrank_orchestrate/log.txt`

## Suggested Git Commands

Run from the repository folder:

```powershell
git status --short
git add .gitignore .env.example AGENTS.md CLAUDE.md README.md problem_statement.md code dataset output.csv code.zip solution_walkthrough.ipynb PUSH_CHECKLIST.md
git status --short
git commit -m "Add calibrated evidence review agent"
git push
```

Before committing, confirm `.env` is not listed.
