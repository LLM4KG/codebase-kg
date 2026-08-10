# Mock dry-run artifacts (WI4)

Archived output of the **mock** Phase 1a validation-pilot run — the end-to-end plumbing
test described in the WI4 summary of `docs/phase_2/phase-2-1a-implementation.md`.
Generated with the orchestrator's mock generator (`mock: true` in every
`metadata.json`), so the diffs are fixtures, not model output.

Moved here on 2026-07-22 so the real (`anthropic/claude-sonnet-4-6`) pilot run can
write to the same `run_id` namespaces without its results appending underneath the
mock ones in `results.jsonl`.

## Layout

Mirrors the repo layout, so any subtree can be restored by moving it back to the
identically-named directory at the repo root:

```
_mock_dryrun/
├── candidate_artifacts/{claude_primary,qwen_robustness}/   # 30 + 10 candidates
├── harness_results/{claude_primary,qwen_robustness}/       # per-candidate JSON + results.jsonl
└── experiment_logs/{claude_primary,qwen_robustness}/       # LLM call logs
```

## What it evidences

- 40/40 candidates stage-classified, 0 harness crashes
- 30 `test_pass` (claude_primary) + 10 `build_fail` (qwen_robustness)

These are **fixture outcomes**, not a result about retrieval quality. They establish
that config → retrieve → prompt → generate → extract diff → harness runs end to end.

## Not archived here

- `harness_results/calibration/` — WI5 timeout-calibration evidence, still live; backs the
  frozen values in `conditions/timeouts.toml`.
- `harness_results/entrypoint_verify/` — *deleted 2026-07-23.* It was real-model smoke
  evidence for the lenient `git apply --recount -C0` fallback, but its `apply_mode` labels
  predate the three-tier split and now read as the opposite of the truth. The full
  `claude_primary` leg supersedes it. See the decision-log entry "`git apply -C0` was
  masking mis-placed patches".

## Caveat

Predates the harness changes of 2026-07-22 — `harness_output.json` files here have no
`stage_detail` or `apply_mode` keys, and were produced by an entrypoint without the
lenient-apply fallback. Do not compare their stage counts against the real run's.
