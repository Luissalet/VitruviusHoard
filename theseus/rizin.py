"""Static Rizin commands against one retained artifact, admitted from a read-only grammar."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

OPERATIONS = [
    {"name": "rizin.command", "title": "Rizin · Orden estática",
     "description": "Ejecuta una orden de Rizin de lectura (información del binario, desensamblado, volcado hexadecimal, análisis, referencias, búsqueda) sobre una copia del artefacto, en modo sandbox y sin scripts, plugins de usuario, shell, escritura ni redirecciones. Devuelve la salida cruda con su SHA-256.",
     "worker": "python", "inputSchema": {"type": "object", "additionalProperties": False, "required": ["command"], "properties": {
         "command": {"type": "string", "minLength": 1, "maxLength": 400},
         "analysis": {"type": "string", "enum": ["none", "aa", "aaa"]},
         "max_output_bytes": {"type": "integer", "minimum": 1, "maximum": 16 * 1024 * 1024}}}},
]

# Read-only command families. Each name may carry a trailing j (JSON) or q (quiet) output mode.
COMMANDS = {
    # binary information
    "i", "ia", "iI", "ie", "iE", "ii", "il", "is", "iS", "iSS", "iz", "izz", "ir", "ih", "iH", "iV", "ic", "iM", "iT",
    # printing
    "pd", "pD", "pdf", "pi", "pI", "px", "pxw", "pxq", "pxh", "ps", "psz", "psw", "p8", "pc",
    # analysis and references (in-memory only; nothing is saved)
    "aa", "aaa", "af", "afl", "afll", "afi", "afb", "afv", "ax", "axt", "axf", "agf", "agc",
    # flags and search
    "f", "fs", "/", "/x", "/a", "/R", "/v",
    # expressions
    "%v", "%vi", "%X",
}
ARGUMENTS = re.compile(r"[A-Za-z0-9_.:+\-*/, ]*")
ADDRESS = re.compile(r"[A-Za-z0-9_.+\-*]+")
GREP = re.compile(r"\?|[A-Za-z0-9_.\-]+")
DEFAULT_OUTPUT_BYTES = 16 * 1024 * 1024
STDERR_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 300


def engine():
    candidates = [os.environ.get("THESEUS_RIZIN"), shutil.which("rizin"),
                  "D:/LocalAI/tools/rizin-0.9.1/unpacked/rizin-win-installer-clang_cl-64/bin/rizin.exe"]
    return next((str(Path(value).resolve()) for value in candidates if value and Path(value).is_file()), None)


def admit(command):
    """The command as Rizin will receive it, or ValueError naming why it is not admitted.

    One command only: separators, pipes, redirection, shell escapes, quoting, interpolation,
    iterators and temporary settings (@@, @e:, @f: ...) are outside the grammar.
    """
    if not isinstance(command, str) or not 1 <= len(command) <= 400:
        raise ValueError("command must be 1 to 400 characters")
    if any(ord(character) < 0x20 or ord(character) > 0x7e for character in command):
        raise ValueError("command must be printable ASCII on one line")
    text = command.strip()
    grep = None
    if "~" in text:
        text, grep = text.split("~", 1)
        if not GREP.fullmatch(grep):
            raise ValueError("Only a plain ~word or ~? filter is admitted after the command")
        text = text.rstrip()
    address = None
    if "@" in text:
        text, address = text.split("@", 1)
        address = address.strip()
        if not ADDRESS.fullmatch(address):
            raise ValueError("Only '@ <address or symbol>' is admitted; @@ iterators and @x: modifiers are not")
        text = text.rstrip()
    name, _, arguments = text.partition(" ")
    base = name[:-1] if name not in COMMANDS and name[-1:] in {"j", "q"} else name
    if base not in COMMANDS:
        raise ValueError(f"Rizin command '{name}' is not in the read-only set: " + ", ".join(sorted(COMMANDS)))
    if not ARGUMENTS.fullmatch(arguments):
        raise ValueError("Arguments may contain letters, digits, spaces and . : + - * / , only")
    return name + (" " + arguments.strip() if arguments.strip() else "") + (" @ " + address if address else "") + ("~" + grep if grep else "")


def _drain(stream, sink, limit, state):
    while True:
        chunk = stream.read(65536)
        if not chunk:
            return
        room = limit - len(sink)
        if room > 0:
            sink += chunk[:room]
        if len(chunk) > room:
            state["truncated"] = True
            return


def run_command(source, parameters, output, expected_sha256):
    executable = engine()
    if not executable:
        raise ValueError("Install free Rizin or set THESEUS_RIZIN to rizin")
    command = admit(parameters.get("command"))
    analysis = parameters.get("analysis", "none")
    limit = parameters.get("max_output_bytes", DEFAULT_OUTPUT_BYTES)
    work = output.parent / "rizin-work"
    work.mkdir(exist_ok=True)
    snapshot = work / "artifact.bin"
    snapshot.write_bytes(source.read_bytes())
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_sha256:
        snapshot.unlink()
        raise ValueError("Artifact changed before a stable snapshot could be read")
    # User settings, scripts and plugins are not loaded, and Rizin's own configuration paths point into the job folder.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("RZ_")}
    environment.update(HOME=str(work), USERPROFILE=str(work), XDG_CONFIG_HOME=str(work), XDG_DATA_HOME=str(work), XDG_CACHE_HOME=str(work))
    version = subprocess.run([executable, "-v"], capture_output=True, timeout=60, env=environment).stdout.decode("utf8", "replace").strip()
    argv = [executable, "-NN", "-q", "-e", "cfg.sandbox=true", "-e", "scr.color=0", "-e", "scr.interactive=false",
            "-e", "scr.utf8=false", "-e", "cfg.fortunes=false", "-e", "io.cache=true"]
    if analysis != "none":
        argv += ["-c", analysis]
    argv += ["-c", command, str(snapshot)]
    stdout, stderr, state = bytearray(), bytearray(), {"truncated": False}
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=work, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    readers = [threading.Thread(target=_drain, args=(process.stdout, stdout, limit, state), daemon=True),
               threading.Thread(target=_drain, args=(process.stderr, stderr, STDERR_BYTES, {"truncated": False}), daemon=True)]
    for reader in readers:
        reader.start()
    completion = "complete"
    while process.poll() is None:
        if state["truncated"]:
            process.kill()
            completion = "unknown"
            break
        if time.monotonic() - started > TIMEOUT_SECONDS:
            process.kill()
            completion = "timeout"
            break
        time.sleep(0.05)
    process.wait()
    for reader in readers:
        reader.join(timeout=10)
    if state["truncated"] and completion == "complete":
        completion = "unknown"
    raw = bytes(stdout)
    text = raw.decode("utf8", "replace")
    after = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    snapshot.unlink(missing_ok=True)
    original_after = hashlib.sha256(source.read_bytes()).hexdigest()
    parsed = None
    if completion == "complete" and command.split(" ")[0].endswith("j") and "~" not in command:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    limitations = ["Raw output is authoritative; JSON is parsed only when a j-suffixed command returns valid JSON.",
                   "Commands run against a private copy in sandbox mode with io.cache, so writes stay in memory and nothing is saved.",
                   "Analysis (aa/aaa) is recomputed on every call; results depend on Rizin's heuristics and version."]
    if text.encode("utf8") != raw:
        limitations.append("Output contained bytes that are not UTF-8; they were replaced in stdout, and stdout_sha256 hashes the original bytes.")
    if state["truncated"]:
        limitations.append(f"Output exceeded {limit} bytes and was cut; the process was stopped, so completion is unknown.")
    return {"engine": {"executable": executable, "sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(), "version": version},
            "command": command, "analysis": analysis, "argv": argv[:-1] + ["<artifact snapshot>"],
            "exit_code": process.returncode, "completion": completion,
            "stdout": text, "stdout_bytes": len(raw), "stdout_sha256": hashlib.sha256(raw).hexdigest(), "stdout_truncated": state["truncated"],
            "stderr": bytes(stderr).decode("utf8", "replace"), "json": parsed,
            "artifact": {"sha256_before": expected_sha256, "snapshot_sha256_after": after, "sha256_after": original_after,
                         "changed": original_after != expected_sha256 or after != expected_sha256},
            "limitations": limitations}
