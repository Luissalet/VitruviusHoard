# Causal performance workshop

Part of Theseus (`theseus/perf.py`), built on the equivalence runner (`theseus/equivalence.py`) and the ordinary
Theseus job store. Tools: `theseus_perf_profile` (`POST /api/projects/{id}/perf/profile`) and `theseus_perf_compare`
(`POST /api/projects/{id}/perf/compare`). Both start a background job (`result.kind` is `perf_profile` /
`perf_compare`); read it with `theseus_job_read`, cancel it with `theseus_job_cancel`.

## Profile

```json
{"command": {"argv": ["python", "app.py"], "env": {}, "timeout_seconds": 60},
 "input": {"args": [], "stdin": "", "files": {"data.json": "..."}, "db": {"path": "app.db", "seed_sql": "..."}},
 "warmup": 1, "runs": 5, "model_functions": ["predict", "*.infer"], "top": 10}
```

Each run happens in a fresh sandbox with the same input. Warm-up runs are discarded. Every measured iteration makes one
unprofiled run (wall-clock) and one profiled run:

- Python commands (`python script.py` or `python -m module`) run under **cProfile**. Self time of each function is
  attributed to `database` (sqlite3, SQLAlchemy and other drivers), `serialization` (json, pickle, marshal, yaml...),
  `rendering` (Jinja2, Mako, Django templates, `string.Template`), `network` (sockets, ssl, http clients),
  `model` (functions matching `model_functions`, matched against the function name, `file:function` and `module.function`,
  plus library helpers reachable only from them), `waiting` (sleep, lock and select waits), `cpu_user` (files under the
  script folder, cwd or `user_paths`) and `other`. Library helpers called only from one categorised function inherit its
  category.
- The result gives, per category, median/p90/min/max of seconds and of share across runs, the dominant category
  (`profile.primary_category`, `profile.diagnosis`) and the top hotspots with `file:line`. For C functions the line is
  the call site found by scanning the calling function for the method name (`call_lines`).
- `segments` gives wall-clock segments: process total for commands; connect, wait for first byte and download for HTTP.

### HTTP mode

`"http": {"request": {"method": "GET", "path": "/"}, "ready_timeout_seconds": 20, "port_env": "PORT"}` starts the command
as a server on a free port (`{port}` placeholder and the `PORT` variable), waits until it accepts connections, runs the
warm-up requests and the measured ones (new connection each), and profiles the server **only during each request** with
a per-thread profile hook (cProfile cannot attribute a multi-threaded server correctly). Idle and blocked time of server
threads is reported under `waiting` and excluded from the shares.

## Compare

`before` and `after` are command specs. Each may add `source_dir` (a directory) or `git: {repo, ref}` (a commit, tag or
branch extracted with `git archive`); the copy is available as `{src}` in `argv`, `cwd` and `env`. Both versions are
measured with the same `input`, interleaved (A,B,B,A,...) to cancel drift.

- `total`: median wall-clock before/after, relative change, speedup, 95% bootstrap interval of the median change, the
  Mann-Whitney U p-value (exact permutation of the observed ranks up to 20000 arrangements, normal approximation with
  tie correction beyond) and `significant` (p < `alpha`, default 0.05, and an interval that excludes 0). With fewer than
  4 runs per version a difference can never reach p < 0.05.
- `categories`: the same test on the profiled seconds of each category.
- `equivalence`: outputs are checked with the equivalence runner (fresh sandboxes; exit code, stdout, stderr, files,
  SQLite) for the measured input plus any `check_inputs`; `normalisers` follow the equivalence rules. For HTTP the status
  and body hash are compared.
- `verdict.status`: `faster`, `slower`, `no_significant_change`, or `failed` when outputs differ (even if faster).

## Limitations

- Shares are profiler self time and cProfile inflates call-heavy code; they locate the dominant cost, wall-clock
  figures come from the unprofiled runs.
- Only Python invocations are profiled; any other command gets wall-clock segments and no attribution. Python flags
  before the script (for example `-u`) disable profiling for that command.
- A command that starts threads is attributed less reliably (cProfile limitation); servers use the hook instead.
- Time inside C extensions is attributed to the Python function that called them unless the call is a named C function.
- No CPU pinning, no isolation from other load on the machine, no distributed or JS/Node profiling. Repeat measurements
  when other work is running.
- Output equality covers the measured input and `check_inputs` only; it is not whole-program equivalence.
