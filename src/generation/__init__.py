"""PHASE 2 — code generation + pilot orchestration (Work item 4).

Wires the per-candidate pipeline end-to-end: resolve config -> build retriever ->
retrieve() -> build_generation_prompt -> generator LLM call -> extract unified diff
-> run_candidate (harness). Reuses the WI2 harness, WI3 retrievers, the LLM logger,
and the config loaders — this package only adds the generator step, the diff
extractor, and the run orchestrator.
"""
