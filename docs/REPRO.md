# Reproducible failure diagnosis

Part of Theseus. Implemented in `theseus/repro.py`; it reuses the equivalence runner (fresh sandbox per execution) and the
safe expression language of the rules bank.

**Scope.** A failure is reproduced and minimised only in fresh sandboxes on this machine and environment. A smaller input
that keeps the same failure signature is not a root-cause proof, and "no longer reproduces" does not prove a defect fixed
for other inputs.

## Report

```json
{
  "command": {"argv": ["python", "app.py"], "cwd": null, "env": {}, "timeout_seconds": 30},
  "stdin": "...", "files": {"data/in.csv": "text or {\"base64\": ...}"}, "env": {"MODE": "strict"},
  "description": "Expected X, observed Y",
  "expected_predicate": "int(stdout) == 26",
  "signature": {"exit_code": 1, "stderr_regex": "^ValueError", "stdout_regex": "...", "timed_out": false, "predicate": "..."}
}
```

The failure signature is the fixed point. If `signature` is omitted it is derived from the first observation: timeout;
non-zero exit code plus the exception name on the last stderr line; or, for a silent wrong output, `not (expected_predicate)`.
`exit_code` may be an integer or `"nonzero"`. Predicates use the same sandboxed expression language
(`stdin exit_code stdout stderr output_files timed_out`).

## `theseus_repro_create`

A background job (`result.kind == "repro_create"`, poll with `theseus_job_read`):

1. Execute in a fresh sandbox twice. No failure, a different failure or a failure only once give `not_reproduced` or
   `flaky`; nothing is minimised and no bundle is written.
2. Delta-debug (ddmin) in this order: environment variables, whole input files, stdin lines, file lines, stdin characters,
   file bytes. Every candidate re-executes the program and is accepted only if the same signature is observed (a
   different error is rejected). `max_runs` (default 300) bounds executions; exhaustion keeps the last completed stage.
3. Confirm the minimal inputs twice more with uncached executions, then write the bundle.

## Bundle

A directory (default under the Theseus data folder, or `output_dir`):

- `repro.json` manifest (format `theseus-repro/1`, command, signature, minimisation trail, environment, manifest hash)
- `inputs/stdin.txt`, `inputs/files/...`
- `run.sh` (POSIX) and `run.cmd` (Windows, CRLF): copy the inputs into a temporary directory, set the recorded environment
  variables, run the command with stdin and print `exit code: N`. Extra arguments replace the recorded command, for example
  `./run.sh python fixed.py`.
- `expected_signature.json`, `environment.json`, `README.txt`

Environment fingerprint: Python and Node versions, OS, machine, relevant environment variables (the report's plus
LANG/LC_ALL/TZ/PYTHON* when set), SHA-256 of every input and of the program files named in argv.

## `theseus_repro_verify`

Runs the bundle (by `bundle_dir` or the create job id as `repro_id`) in a fresh sandbox, optionally with an `argv` override
(for instance a fixed version) and `attempts` (1-10). Inputs are checked against the recorded hashes first and a modified
bundle is refused. Verdict `reproduces` (signature observed at least once) or `no_longer_reproduces`, with
`still_fails_differently` when the program fails with another signature, plus differences between the recorded and current
Python/Node/OS. Saved as an ordinary job.

## Limits

stdin is text (UTF-8) and the command receives no extra arguments beyond `argv`; a single execution per candidate, no
interleaving or concurrency; no network, clock or locale isolation beyond the recorded variables; Windows scripts quote
arguments with the standard command-line rules and double `%`, so unusual values containing `^` or `!` may need manual
review; minimisation is local, not global; the bundle contains the (possibly sensitive) inputs; Windows scripts were
checked by content, not executed, on this Linux host; no web UI view.
