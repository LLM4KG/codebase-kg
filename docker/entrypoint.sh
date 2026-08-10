#!/bin/bash
set -o pipefail
OUT=/harness/output
mkdir -p "$OUT"
echo "harness_error" > "$OUT/stage.txt"

cd /app

# Stage 0: baseline commit.
#
# `stage_build_context()` excludes `.git` from the build context, so /app is a
# plain directory, not a repository. `git apply` doesn't care — it patches the
# working tree — but two other things do, and one of them has been silently
# broken since WI2: Stage 2's `git diff --name-only HEAD -- package.json` has
# never once run successfully. It printed `git diff --no-index` usage text to
# stderr on every candidate of the 2026-07-23 leg (visible in each result's
# `stderr` field) and `grep -q .` found nothing in the empty stdout, so `npm ci`
# was never triggered. No pilot task touched package.json, so nothing failed
# because of it — but the install gate was decorative.
#
# The image now ships a repo with a build-time baseline commit (see the
# Dockerfiles). Re-commit here, at container start, so the task's test files —
# bind-mounted into /app *after* the image was built — are part of the baseline
# rather than showing up as part of the candidate's change.
git add -A > /dev/null 2>&1   # no -q: the image's git 2.30 rejects it
git commit -q --allow-empty -m "harness baseline (with task tests)" 2>/dev/null

# Stage 1: apply the candidate edit.
#
# EDIT_FORMAT selects how the model was asked to express its change:
#   unified_diff   — a git patch; applied by the three-tier ladder below
#   search_replace — exact-match SEARCH/REPLACE blocks
#   whole_file     — complete file bodies
# The latter two arrive as a JSON edit script and are applied by
# /harness/apply_edits.js, which owns its own trust tiers and failure reasons.
#
# Whichever path runs, it must leave behind:
#   apply.log         — presence marks "the apply step ran"
#   apply_mode.txt    — the trust tier (absent + apply.log ⇒ "strict")
#   apply_reason.txt  — on failure only: the attributable cause
export HARNESS_OUT="$OUT"
EDIT_FORMAT="${EDIT_FORMAT:-unified_diff}"

# Derive an attributable cause from git's own prose. `diff_apply_fail` alone
# conflates "couldn't count lines" with "invented a path" with "invented the
# code" — in the 2026-07-23 pilot all 15 floor candidates shared that one label
# for three different reasons, which is precisely what the floor-vs-KG reading
# turned on.
derive_git_reason() {
  if grep -q "No such file or directory" "$OUT/apply_stderr.log" 2>/dev/null; then
    echo "file_not_found"
  elif grep -qE "corrupt patch|patch fragment without header" "$OUT/apply_stderr.log" 2>/dev/null; then
    echo "line_arithmetic"
  elif grep -q "does not apply" "$OUT/apply_stderr.log" 2>/dev/null; then
    echo "context_mismatch"
  else
    echo "empty_edit"
  fi
}

if [ "$EDIT_FORMAT" = "unified_diff" ]; then
  # A three-tier ladder, strictest first.
  #
  # LLM-generated patches routinely carry malformed `@@` line counts (the hunk
  # body length disagrees with the header), which plain `git apply` rejects.
  # `--recount` recomputes those counts from the body while STILL matching
  # context, so a patch with bad arithmetic but correct content applies and one
  # aimed at the wrong location is rejected.
  #
  # `-C0` additionally drops context matching, placing hunks by line number with
  # no verification. That is not a safety net — it silently applies patches at the
  # wrong location. Observed: a candidate targeting `@@ -100` for code that lives
  # at line 286 was applied anyway, splicing statements mid-expression and turning
  # what should have been diff_apply_fail into build_fail. It therefore gets its
  # own tier so results resting on it can be quarantined rather than counted.
  #
  # Tiers, recorded in apply_mode.txt:
  #   strict      — plain `git apply`; patch was well-formed
  #   recount     — line counts fixed, context still verified; TRUSTWORTHY
  #   recount_c0  — context matching disabled; placement UNVERIFIED, quarantine
  #
  # Each tier's stderr is preserved even when a later tier succeeds.
  git apply /harness/candidate.diff > "$OUT/apply.log" 2> "$OUT/apply_stderr.log"
  if [ $? -ne 0 ]; then
    STRICT_REASON=$(derive_git_reason)
    echo "strict git apply failed; retrying with --recount (context preserved)" \
      >> "$OUT/apply_stderr.log"
    git apply --recount /harness/candidate.diff \
      >> "$OUT/apply.log" 2>> "$OUT/apply_stderr.log"
    if [ $? -ne 0 ]; then
      echo "--recount failed; retrying with --recount -C0 (placement UNVERIFIED)" \
        >> "$OUT/apply_stderr.log"
      git apply --recount -C0 /harness/candidate.diff \
        >> "$OUT/apply.log" 2>> "$OUT/apply_stderr.log"
      if [ $? -ne 0 ]; then
        # Report the *last* tier's cause: with the arithmetic already recomputed,
        # what remains is the real disagreement with the file. Reporting the
        # strict tier's `line_arithmetic` here would credit every failure to
        # bookkeeping and hide the path/content failures underneath it.
        derive_git_reason > "$OUT/apply_reason.txt"
        echo "diff_apply_fail" > "$OUT/stage.txt"
        exit 0
      fi
      echo "recount_c0" > "$OUT/apply_mode.txt"
    else
      echo "recount" > "$OUT/apply_mode.txt"
    fi
    echo "strict-tier cause: $STRICT_REASON" >> "$OUT/apply_stderr.log"
  fi
else
  touch "$OUT/apply_stderr.log"
  node /harness/apply_edits.js /harness/candidate.diff > "$OUT/apply.log" 2>> "$OUT/apply_stderr.log"
  if [ $? -ne 0 ]; then
    rm -f "$OUT/apply.log"          # keep "apply.log exists ⇒ the edit applied"
    echo "diff_apply_fail" > "$OUT/stage.txt"
    exit 0
  fi
fi

# A canonical unified diff of what actually landed, for every format. Restores
# patch-based comparability — a `whole_file` candidate and a `unified_diff` one
# become directly diffable against each other and against the reference patch —
# for two git calls. Staged rather than plain `git diff` so newly created files
# (P3 creates one) appear as additions instead of vanishing as untracked.
git add -A > /dev/null 2>&1   # no -q: the image's git 2.30 rejects it
git diff --cached > "$OUT/applied.patch" 2>/dev/null

# Stage 2: install, only if the change touched package manifests. `--cached`
# because Stage 1 just staged everything.
if git diff --cached --name-only HEAD -- package.json package-lock.json | grep -q .; then
  npm ci > "$OUT/install.log" 2>&1
  if [ $? -ne 0 ]; then
    echo "install_fail" > "$OUT/stage.txt"
    exit 0
  fi
fi

# Stage 3: build (project-conditional)
if [ "$RUN_BUILD" = "1" ]; then
  eval "$BUILD_COMMAND" > "$OUT/build.log" 2>&1
  if [ $? -ne 0 ]; then
    echo "build_fail" > "$OUT/stage.txt"
    exit 0
  fi
fi

# Stage 4: test
eval "$TEST_COMMAND" > "$OUT/test_stdout.log" 2> "$OUT/test_stderr.log"
TEST_EXIT=$?
echo "$TEST_EXIT" > "$OUT/exit_code.txt"

if [ $TEST_EXIT -eq 0 ]; then
  echo "test_pass" > "$OUT/stage.txt"
elif grep -qE "Test suite failed to run|Cannot find module|SyntaxError:|FATAL ERROR|Segmentation fault" \
       "$OUT/test_stdout.log" "$OUT/test_stderr.log" 2>/dev/null; then
  echo "setup_crash" > "$OUT/stage.txt"
else
  echo "test_fail" > "$OUT/stage.txt"
fi
