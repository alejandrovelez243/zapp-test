# backend/evals — Eval Datasets

This directory holds the committed `pydantic-evals` datasets (YAML) for the Zapp Global
Philosophy School platform.  The datasets are version-controlled so every Case change is
reviewable in git and maps 1:1 to a numbered acceptance criterion in the corresponding
`specs/<feature>/requirements.md` file (EARS notation).

## Datasets

| File | Cases | Spec |
|---|---|---|
| `datasets/multilingual.yaml` | `multilingual-001..014` | `specs/multilingual/requirements.md` |

## Runner

These Cases are consumed by the `evaluation` feature's `evals.run` module
(`backend/evals/run.py`), which is implemented in the `evaluation` spec.  The runner
attaches LLMJudge language-fidelity evaluators and deterministic `active_lang` /
`needs_review` assertions to each Case, calls `Dataset.evaluate_sync(task)`, computes
thresholds, and exits non-zero on any breach.  This directory contains the committed
dataset only — no runner code lives here yet.

## Special metadata flags (consumed by the runner)

- `simulate_low_confidence: true` — runner mocks the lingua detector to return a
  disagreeing result so `lang_confidence` falls below `lang_confidence_min` (0.55).
- `simulate_detector_failure: true` — runner mocks the detector's error path
  (`DetectionResult(lang=None, confidence=0.0, is_reliable=False, error=...)`).
- `assert_all_nine_fields: true` — runner verifies every field of the per-turn JSON
  contract is present and non-null in the output.
- `lang_confidence_min` / `lang_confidence_max` — runner asserts the actual
  `lang_confidence` value is within the specified bound.
- `expected_reply_lang` — runner's language-fidelity evaluator detects the reply
  language with `lingua` and asserts it matches this ISO 639-1 code.
