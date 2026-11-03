# Dependency upgrade rehearsal

Part of Babel (`babels_hoard/rehearsal.py`), exposed as the MCP tool and HTTP endpoint `api_upgrade_rehearsal`
(`POST /api/agent/api_upgrade_rehearsal`). It answers "what breaks if this project moves package X to version Y?"
without touching the project or its environment.

It reuses Babel's own machinery: the griffe indexer (`indexing`), the call/attribute resolution of `api_check_code`
(`checker`, which now optionally records every resolved use) and the dependency reader (`deps`). There is no second
documentation index.

## What it does

1. **Two isolated source trees.** The current version is read from the project's environment (read only), from
   `old_path`, or installed with `pip install --target` into a temporary folder (`old_version`/`old_requirement`).
   The target version is installed the same way (`target_version` or `requirement`, extra `pip_args` such as
   `--no-index`). Nothing is installed into the project's environment. `new_path` / `old_path` skip pip entirely.
2. **API diff.** Both versions are indexed into scratch databases. Public symbols are compared: removed symbols,
   moved symbols (same name, kind and signature with exactly one new home), changed signatures (parameters added or
   removed, renamed keywords matched one-to-one by position, kind and default, changed defaults, kind changes,
   reordered positionals, async/static changes, new deprecations, return annotation changes).
3. **Use classification.** Every Python file mentioning the package is checked with the existing checker against both
   versions. A use is
   - **broken** when the checker proves it no longer fits the target (removed or moved import, unknown attribute,
     unexpected keyword, missing required argument, too many positional arguments) and the same finding did not exist
     before;
   - **at risk** when it still resolves but the default of a parameter it relies on changed, the symbol is newly
     deprecated, the return annotation changed, the docstring/changelog mentions a behaviour change, or a removed
     name appears on a value of unknown type (text match, never "broken");
   - **ok** otherwise. Uses the checker cannot resolve are counted as unchecked.
4. **Migration plan.** `plan.mechanical_edits` holds exact edits (file, line, column span, old and new text, reason),
   only for a renamed keyword argument or a moved `from ... import` with one certain new location (single-line
   statements; mixed statements are split). Everything else is in `plan.manual` with the reason. `plan.diff` is a
   unified diff of the mechanical edits.
5. **Before/after tests (optional, `run_tests`).** The project is copied three times (no `.git`, virtualenvs or caches):
   the old version, the new version unedited, the new version with the mechanical edits. The test command
   (default `python -m pytest -q -p no:cacheprovider -rfE` when test files exist, or `test_command`) runs in each with
   the corresponding version first on `PYTHONPATH`. Reported: `regressions` (failing now, passing before),
   `regressions_after_edits`, `fixed_by_edits` and `partly_fixed_by_edits` (a collection error that turns into
   individual failures). The user's project folder is never written.

## Limitations

- Python only. JavaScript/TypeScript requests are refused with `unsupported_language`.
- Classification is based on indexed signatures and statically resolved call sites. Behaviour changes that no
  docstring, changelog or default value reveals are invisible; values of unknown type, dynamic access and guarded code
  stay unchecked. A package above the indexing cap is partial and absences are then not provable.
- Moved symbols are detected for top-level functions and classes whose name, kind and signature (or member names) match
  exactly one new location; renamed symbols are listed as removed with no replacement.
- Changelogs are read only when found beside the installed target or passed in `changelog_paths`.
- Install of the target needs network (or `--no-index` with a local source) and a pure-Python package or a compatible
  wheel; the test run puts the target first on `PYTHONPATH`, which cannot replace compiled extensions already loaded
  from elsewhere.
