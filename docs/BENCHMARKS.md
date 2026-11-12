# Versioned reconstruction measurements

The Rehacer screen includes a reconstruction benchmark with all 70 references from the v1 corpus linked by the research catalogue. The source dataset revision is `d7fcb4c06fee6563e88675fb7ed21135cb26e693`. Its entry identifiers, task content hashes and 46,916 published case counts ship in `vitruvius_hoard/benchmarks/corpus.json`.

## Execution

Enable the Design module and open Rehacer. Enter the version being measured, choose the complete corpus or one reference, select copy or model reconstruction, and set the round budget. Default measurements use copy, one round, 1440 and 390 px, a 98% pass threshold and 10% channel tolerance. The MCP and REST arguments also expose widths and thresholds.

The first evaluation prepares a Linux reference runtime using the installed container engine. Its base images have fixed digests. The runtime caches the dependency wheel versions declared by the corpus and each reference installs its original hash-locked requirements offline. It downloads reference fixtures from the pinned dataset revision, verifies every file against its published Git blob or large-file checksum, and retains that manifest. Each case starts an unchanged reference with fresh local state. The reference closes after the ordinary `remake_start` job finishes. Reconstruction uses the existing browser and, in rebuild or repair rounds, the configured global model.

Identical files share a checksum-verified download cache. Remote rate-limit responses honour `Retry-After` or the published reset time before retrying. The entry route must respond successfully before it is captured, so a backend error page cannot become a successful reference measurement.

The reference filesystem is reconstructed inside Linux directly from verified blobs and the original member manifest. This preserves case-sensitive names on Windows. Original fixture archives are restored with their relative paths, then their own compilation script runs. Node references install their original package lock with `npm ci` and run their own build script before starting the resulting standalone server. This initial build requires registry access. Each batch pins the prepared runtime image ID. Implementation and runtime source fingerprints use UTF-8 text with normalized line endings.

The container engine must be running. Copy measurements need the existing browser dependencies (`pip install -e '.[render]'`). Explicit `runtime_kind="native"` uses the current interpreter and installed reference dependencies (`.[benchmark]`). Several reference backends require Linux libc. The default container runtime supplies that environment on Windows.

## Retained evidence

Each invocation creates a new evaluation under `data/design/benchmarks/runs/<id>/` in the normal software profile. It records the caller's version label, an implementation SHA-256 covering Rehacer, the browser, parity and the evaluation code, the corpus manifest, reference hashes, settings, environment, every case status, remake IDs, models, per-round and per-width scores, timestamps and PNG hashes. The normal Rehacer and Parity reports retain the reference, candidate and difference images. Download results JSON from the screen or its export route.

The measured mean uses cases with a measured round. Coverage, errors, passes and the selected denominator are reported separately. A completed batch can contain failed cases. A case without a score stays unmeasured. Stop preserves completed results. Resume processes pending or interrupted cases with the same implementation. A new invocation repeats failures and records a new version without overwriting an earlier result.

Version comparison requires identical corpus, selection, runtime environment, reference hashes, observed browser and measurement settings. Each measured case retains its browser version and launcher. Comparison reports the delta over paired measured cases with its own denominator. Different settings, browser observations or reference bytes return explicit comparison differences. Stored result snapshots remain readable when a remake is subsequently edited or deleted. Their original report files are owned by Rehacer and follow its normal deletion behaviour.

## Measurement scope

The metric is `vitruvius-stable-pixels/1`, frozen full-page visual parity of each reference's entry page at the selected widths. Rehacer captures the reference twice per width, masks noise, scores screens and retains the best round. The default copy mode reproduces the captured composition. Each retained result records the actual mode and budget.

The upstream benchmark's official reward requires functional test cases plus flat-baseline-normalized RGB SSIM of at least 0.99 at every checkpoint. This implementation leaves that reward as `null`. Its 70 entry-page measurements do not execute the 46,916 hidden cases, navigation sequences, account flows, restarts or mail/payment integrations. Those case counts identify the source corpus and are excluded from the visual score denominator. Existing Rehacer refusals and runtime/download failures remain visible as failed, unmeasured cases.

## Product entry points

MCP tools are `benchmark_catalog`, `benchmark_start`, `benchmark_get`, `benchmark_list`, `benchmark_compare`, `benchmark_stop` and `benchmark_resume`. Cold native discovery lists their schemas without starting reference processes or engines. Running them uses the normal Design module owner.

```json
{"name":"benchmark_start","arguments":{"version":"release-or-commit","mode":"copy","max_rounds":1}}
```

REST provides `GET /design/api/benchmarks/catalog`, `GET|POST /design/api/benchmarks/runs`, `GET /design/api/benchmarks/runs/<id>`, `POST /design/api/benchmarks/runs/<id>/stop`, `POST /design/api/benchmarks/runs/<id>/resume`, `GET /design/api/benchmarks/runs/<id>/export` and `POST /design/api/benchmarks/compare` with `before` and `after` IDs.

## Provenance

The corpus was located through [the research catalogue](https://github.com/reacher-z/Awesome-REA). Its [source repository](https://github.com/TIGER-AI-Lab/WebsiteBench), [task list](https://github.com/TIGER-AI-Lab/WebsiteBench/blob/main/docs/tasks.md) and [dataset](https://huggingface.co/datasets/TIGER-Lab/WebsiteBench/tree/d7fcb4c06fee6563e88675fb7ed21135cb26e693) define the pinned references. Benchmark code and task definitions carry Apache-2.0. Reference website content belongs to its respective owners and is distributed for non-commercial research. Downloaded fixtures retain their original bytes and notices in the local evaluation cache.
