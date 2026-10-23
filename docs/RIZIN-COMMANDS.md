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

Source implementation is undergoing area validation, MCP/UI checks and
independent review under task 1154. Installed acceptance and publication require
separate receipts; the previous reviewed package remains installed until then.
