#!/usr/bin/env node
/**
 * Apply a candidate edit script inside the harness container.
 *
 * Consumes the JSON written by `src/generation/edit_formats/base.py:EditScript`
 * and handles the two formats git cannot: `search_replace` and `whole_file`.
 * `unified_diff` never reaches here — `docker/entrypoint.sh` sends it through
 * the original three-tier `git apply` ladder untouched.
 *
 * **Node, not Python, on purpose.** Both harness images are `node:14-bullseye`,
 * but only `docker/takenote/Dockerfile` installs python3. A Python applier would
 * work for one project and silently not exist for the other.
 *
 * Contract with the entrypoint, via files in $OUT:
 *   exit 0 + apply_mode.txt   — applied; the value is the trust tier
 *   exit 1 + apply_reason.txt — did not apply; the value is the attributable cause
 *
 * Everything is all-or-nothing: edits are staged in memory and flushed only once
 * every one of them has resolved. A half-applied script would produce build
 * errors describing a state the model never asked for — the same failure the
 * `recount_c0` tier produced and the reason it is quarantined.
 *
 * Node 14: no `fs.rmSync` recursive quirks relied on, no optional chaining, no
 * `String.replaceAll`. Keep it that way.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO = '/app';
const OUT = process.env.HARNESS_OUT || '/harness/output';
const SCRIPT_PATH = process.argv[2] || '/harness/candidate.diff';

function write(name, value) {
  // `.txt` matters: `read_apply_mode` / `read_apply_reason` in
  // src/harness/runner.py look for exactly these filenames, and a missing
  // apply_mode.txt is silently read as the `strict` git tier.
  fs.writeFileSync(path.join(OUT, name + '.txt'), String(value) + '\n');
}

function fail(reason, detail) {
  write('apply_reason', reason);
  if (detail) {
    fs.appendFileSync(path.join(OUT, 'apply_stderr.log'), detail + '\n');
  }
  process.exit(1);
}

/** Reject anything that would write outside the repo. */
function resolveInRepo(relPath) {
  const full = path.resolve(REPO, relPath);
  if (full !== REPO && full.indexOf(REPO + path.sep) !== 0) return null;
  return full;
}

function countOccurrences(haystack, needle) {
  if (!needle) return 0;
  let count = 0;
  let index = haystack.indexOf(needle);
  while (index !== -1) {
    count += 1;
    index = haystack.indexOf(needle, index + needle.length);
  }
  return count;
}

/**
 * Find `search` in `body`, exactly and exactly once.
 *
 * The one tolerance: a SEARCH block whose last line is the file's last line
 * arrives with a trailing newline the file does not have. That is an artefact of
 * how the block was written down, not a difference in the code, so a
 * newline-trimmed retry is allowed. No other normalisation — no whitespace
 * folding, no indentation guessing. An approximate match that applies is the
 * failure mode this whole format exists to remove.
 */
function locate(body, search) {
  let needle = search;
  let count = countOccurrences(body, needle);
  if (count === 0 && needle.slice(-1) === '\n') {
    needle = needle.slice(0, -1);
    count = countOccurrences(body, needle);
  }
  return { needle: needle, count: count };
}

function main() {
  let script;
  try {
    script = JSON.parse(fs.readFileSync(SCRIPT_PATH, 'utf8'));
  } catch (err) {
    return fail('empty_edit', 'apply_edits: unreadable edit script: ' + err.message);
  }

  const edits = script.edits || [];
  if (edits.length === 0) {
    // "The model tried and I could not parse it" and "the model produced
    // nothing" are different experimental outcomes; the extractor counted which.
    return fail(
      script.malformed_blocks > 0 ? 'malformed_blocks' : 'empty_edit',
      'apply_edits: no applicable edits (malformed_blocks=' +
        (script.malformed_blocks || 0) + ')'
    );
  }

  // Staged writes: relPath -> string body, or null for "delete".
  const staged = Object.create(null);

  function currentBody(full, rel) {
    if (Object.prototype.hasOwnProperty.call(staged, rel)) return staged[rel];
    if (!fs.existsSync(full)) return null;
    return fs.readFileSync(full, 'utf8');
  }

  for (let i = 0; i < edits.length; i += 1) {
    const edit = edits[i];
    const rel = edit.path;
    const full = resolveInRepo(rel);
    if (full === null) {
      return fail('file_not_found', 'apply_edits: path escapes the repo: ' + rel);
    }

    if (edit.op === 'delete') {
      if (currentBody(full, rel) === null) {
        return fail('file_not_found', 'apply_edits: cannot delete missing file: ' + rel);
      }
      staged[rel] = null;
      continue;
    }

    if (edit.op === 'write') {
      staged[rel] = edit.content;
      continue;
    }

    if (edit.op === 'replace') {
      const body = currentBody(full, rel);
      if (body === null) {
        return fail('file_not_found', 'apply_edits: no such file: ' + rel);
      }
      const found = locate(body, edit.search);
      if (found.count === 0) {
        return fail(
          'search_not_found',
          'apply_edits: SEARCH text not found in ' + rel + '\n--- SEARCH ---\n' + edit.search
        );
      }
      if (found.count > 1) {
        // Deliberately fatal. Picking the first match is exactly the guess that
        // `git apply --recount -C0` makes, and it is what put P2's hunks 186
        // lines from their target in the 2026-07-23 leg.
        return fail(
          'ambiguous_match',
          'apply_edits: SEARCH text matches ' + found.count + ' times in ' + rel +
            ' — cannot place it unambiguously\n--- SEARCH ---\n' + edit.search
        );
      }
      const at = body.indexOf(found.needle);
      staged[rel] = body.slice(0, at) + edit.content + body.slice(at + found.needle.length);
      continue;
    }

    return fail('malformed_blocks', 'apply_edits: unknown op: ' + edit.op);
  }

  // Every edit resolved — flush.
  const paths = Object.keys(staged);
  for (let i = 0; i < paths.length; i += 1) {
    const rel = paths[i];
    const full = resolveInRepo(rel);
    if (staged[rel] === null) {
      fs.unlinkSync(full);
    } else {
      fs.mkdirSync(path.dirname(full), { recursive: true });
      fs.writeFileSync(full, staged[rel]);
    }
  }

  if (script.format === 'whole_file') {
    // A body the model abbreviated applies perfectly and means nothing. Same
    // treatment as `recount_c0`: record it, let the run continue, quarantine it
    // at reporting time.
    write('apply_mode', script.elided ? 'whole_file_elided' : 'whole_file');
    if (script.elided) {
      fs.appendFileSync(
        path.join(OUT, 'apply_stderr.log'),
        'apply_edits: WHOLE-FILE BODY ELIDED — placement/completeness UNVERIFIED.\n' +
          'marker: ' + (script.elision_marker || '(unknown)') + '\n'
      );
    }
  } else {
    write('apply_mode', 'exact_unique');
  }
  write('apply_files', paths.length);
  process.exit(0);
}

main();
