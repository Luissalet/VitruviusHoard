# Binary command observations

In **Análisis**, select an artifact and a command operation. The same operations
are available through `theseus_analysis_start` over MCP.

- `rizin.command` keeps its existing read-only grammar, private artifact snapshot,
  sandbox and `-NN` profile. Its existing controls and output remain available.
- `rizin.execute` sends the caller's literal nonempty line with `-N -q -c` against
  the original absolute artifact path. It suppresses user settings/scripts while
  retaining plugins. Unicode, spaces and lines longer than 400 characters remain
  literal; CR, LF and NUL are rejected. Compound engine commands are permitted.

For example, `{"command":"%vi 37*41"}` records an arithmetic observation.
Commands can write files, execute code, contact the network and read external
inputs. Those effects persist; cancelling cannot undo them. The operation does
not close existing native binary sessions. The result records the effective
working directory, engine identity and original artifact identity.

The execution records stdout and stderr separately with original bytes in
base64, hashes, decoded UTF-8 and an explicit replacement flag. A valid U+FFFD
character does not set that flag. Both streams share a 16 MiB raw byte budget
applied inside their readers before buffering. Exactly reaching that size and
then EOF is complete; observing an excess byte marks truncation and stops the
owned process group. A read error is distinct from EOF.

A naturally observed nonzero exit with complete streams remains a complete
observation. A return code or parsed output does not certify the semantic effect
of an arbitrary command. Parent exit alone does not establish completion while
owned descendants or stream handles remain active. Cancellation, enforced output
limits and interrupted collection preserve unknown completion without retrying.
There is no implicit execution timeout; the job can be cancelled explicitly.

Normal Windows descendants belong to a Windows Job established before the new
process resumes. Other platforms use a new POSIX process group. External brokers
and detached groups are outside those ownership scopes. Collection order across
the two pipes is not a global causal order.

The complete JSON and indexed records remain available in **Ejecuciones** and
portable project evidence. Retained reads and recovery use only recorded data;
they neither reopen the original nor execute its command again. An interrupted
observer retains its last published prefix, which may omit later bytes. Initial
launch intent leaves effects unknown if no later checkpoint survives.

The artifact's endpoint hashes do not bind transient changes, plugins, libraries
or other inputs. If the original disappears or cannot be read afterwards, its
after hash and change status stay unknown while the recorded streams survive.
No target-equivalence or arbitrary-command success guarantee is made.

Source validation under task 1154 passed 114 area tests without skips, including
an existing Ghidra session that remained open and returned its original bytes.
Ten workspace/cold-catalogue tests also passed after the discovery description
was updated to acknowledge explicit command effects. Five actual stdio MCP
observations covered arithmetic, a long Unicode line, a change to an original
file, an engine diagnostic and cancellation with a retained prefix. Their five
documents transferred exactly while the original path was absent.

The normal UI created a separate arithmetic observation (899), then displayed
the imported uncertain receipt and its 20-byte prefix. The 390 px view had no
horizontal overflow. The form now names explicit execution and its effects;
the previous generic static-analysis introduction is retained as failed UI
evidence. Private HTTP document delivery was exact; a completed browser download
was not attempted or claimed. The private owner and tab have closed.

An initial oracle used an unsupported echo spelling; a later launch-intent test
omitted its parent directory. Both failed runs are preserved, separately from
the corrected 114-test run. Independent revision 1 then found that a failed
Windows Job assignment could leave the newly created child suspended. The
correction terminates that actual child through its handle before reporting
cleanup success; an assigned Job still handles the normal descendant group.
Creation, assignment and resume fault controls verify real child exit without
executing their marker code. The corrected area passed 117 tests without skips;
the initial failing fault run and independent report remain preserved.

Independent revision 2, full validation, installed acceptance and publication
are pending. The previous reviewed W2 package
remains installed until those steps complete.
