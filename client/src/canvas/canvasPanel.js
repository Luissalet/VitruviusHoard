// Pure helpers of the Canvas screen (no DOM or React: they run under `node --test`).

/** The modes of the canvas toolbar, in order. `handles` only shows when the preview says it supports it. */
export const MODES = ["navigate", "select", "comment", "handles"];

/** Messages the inspector inside the preview sends to its host (see `preview-inspector.js`). */
const FROM_PAGE = new Set(["dock/inspector-ready", "dock/select", "dock/comment-target", "dock/comment-anchors", "dock/comment-focus", "dock/elements"]);

/** True for an inspector message from the visible preview frame: right window, right origin, right envelope. */
export function isCanvasMessage(event, frameWindow, origin) {
  const data = event?.data;
  return Boolean(frameWindow) && event.source === frameWindow && event.origin === origin
    && data?.hoardDock === 1 && FROM_PAGE.has(data.type);
}

/** Which modes this preview supports, from its `dock/inspector-ready` message. */
export function supportedModes(data) {
  const modes = ["navigate"];
  if (Array.isArray(data?.selection)) modes.push("select");
  if (data && "comment_mode" in data) modes.push("comment");
  if (data?.handles === true || (Array.isArray(data?.capabilities) && data.capabilities.includes("handles"))) modes.push("handles");
  return modes;
}

/** The mode the page reports it is in. */
export function modeFromPage(data) {
  if (data?.handles_mode) return "handles";
  if (data?.comment_mode) return "comment";
  if (data?.mode) return "select";
  return "navigate";
}

/** What to post to the preview to enter `mode` (navigate leaves every mode). */
export function modeMessages(mode, current) {
  if (mode === "navigate") {
    if (current === "comment") return [{ type: "inspect/mode", on: false, kind: "comment" }];
    if (current === "handles") return [{ type: "inspect/mode", on: false, kind: "handles" }];
    return current === "select" ? [{ type: "inspect/mode", on: false }] : [];
  }
  return [mode === "select" ? { type: "inspect/mode", on: true } : { type: "inspect/mode", on: true, kind: mode }];
}

/** Translate a click on the host's temporary shield into the preview viewport. */
export function previewPick(frame, { clientX, clientY, shiftKey }) {
  const rect = frame.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const x = (clientX - rect.left) * frame.offsetWidth / rect.width - frame.clientLeft;
  const y = (clientY - rect.top) * frame.offsetHeight / rect.height - frame.clientTop;
  if (x < 0 || y < 0 || x >= frame.clientWidth || y >= frame.clientHeight) return null;
  return { type: "inspect/pick", x, y, additive: shiftKey };
}

/** `tag.class` of an element. */
export function elementLabel(item) {
  const name = (item?.tag || "element") + (item?.classes?.length ? "." + item.classes.slice(0, 2).join(".") : "");
  const text = item?.text ? ` "${item.text.length > 40 ? item.text.slice(0, 39) + "…" : item.text}"` : "";
  return name + text;
}

function activeHistoryEdits(source) {
  const active = new Set();
  const reverted = new Set();
  for (let node = source; node; node = node.previous) {
    if (node.entry.action === "undo-change") reverted.add(node.entry.reverted_change);
    else if (!reverted.has(node.entry.id)) active.add(node.entry.id);
  }
  return active;
}

/** Number transitions and follow the recorded source when an earlier revision is restored. */
export function canvasHistoryEntries({ revisions, history }) {
  const journal = history || [];
  const recorded = new Set(journal.map((entry) => entry.revision));
  const entries = [
    ...revisions.filter((revision) => !recorded.has(revision)).map((revision) => ({ revision })),
    ...journal,
  ];
  const sources = new Map();
  const redoSteps = new Set();
  let source = null;
  entries.forEach((entry, index) => {
    const prior = entries[index - 1];
    if ((entry.action === "edit" && entry.id) || (entry.action === "undo-change" && entry.reverted_change)) {
      source = { entry, previous: source };
    } else if (["undo", "critique-restore", "critique-undo"].includes(entry.action)) {
      // Revision IDs identify source content. Reusing one restores its recorded edit ancestry.
      if (sources.has(entry.revision)) source = sources.get(entry.revision);
      if (entry.action === "undo" && prior?.previous_revision === entry.revision &&
          (prior.action === "undo-change" || (prior.action === "undo" && !redoSteps.has(index - 1)))) {
        redoSteps.add(index);
      }
    }
    sources.set(entry.revision, source);
  });
  const active = activeHistoryEdits(source);
  const latest = entries.at(-1);
  const latestIndex = entries.length - 1;
  let redoRevision;
  if (latest?.previous_revision && ["undo", "undo-change"].includes(latest.action) && !redoSteps.has(latestIndex)) {
    const before = activeHistoryEdits(sources.get(latest.previous_revision));
    if ([...before].some((id) => !active.has(id))) redoRevision = latest.previous_revision;
  }
  return entries.map((entry, index) => ({
    ...entry,
    step: index + 1,
    ...(entry.action === "edit" && entry.id && !active.has(entry.id) ? { undone: true } : {}),
    ...(redoSteps.has(index) ? { action: "redo" } : {}),
    ...(index === latestIndex && redoRevision ? { redoRevision } : {}),
  })).reverse();
}

/** Name a retained snapshot by its position in the catalog, independently of the history step. */
export function canvasRevisionLabel(revisions, revision, es) {
  const index = revisions.indexOf(revision);
  return index < 0 ? null : `${es ? "Versión" : "Revision"} ${index + 1}`;
}

/**
 * The screen context the Dock bridge sends to the host (Faustus) with each change. The host keeps `focus` as
 * `{kind, id, label}` and `summary` up to 400 characters, so the selection and the open comments travel as short text
 * in `summary`. It says exactly what the selection panel holds: `selected N` counts only the active elements of the
 * revision on screen; elements that are gone from it (`expired`) are named apart, without a source position, and are
 * never counted as selected. Comments come first and keep their share (`commentShare` characters at most); the
 * expired notice keeps `expiredShare`; the active selection uses the rest, item by item, and says how many it left
 * out. The agent reads the full detail with the project tools.
 */
export function canvasContext({ project, revision, mode, selection = [], comments = [] }, max = 400, commentShare = 140, expiredShare = 90) {
  if (!project) return { view: "canvas" };
  const clip = (text, size) => (text.length > size ? text.slice(0, Math.max(0, size - 1)) + "…" : text);
  const open = comments.filter((comment) => ["pending", "seen", "answered"].includes(comment.status));
  const active = selection.filter((item) => !item.expired);
  const gone = selection.filter((item) => item.expired);
  const head = clip(`${project.name}${revision ? ` @${String(revision).slice(0, 12)}` : ""}${mode && mode !== "navigate" ? ` · mode ${mode}` : ""}`, 80);
  const notes = open.length ? clip(`open comments ${open.length}: ` + open.map((comment) => `#${comment.n} ${String(comment.note || "").slice(0, 40)}`).join("; "), commentShare) : "";
  const stale = gone.length ? clip(`expired ${gone.length}, not in this revision: ` + gone.map((item) =>
    `${item.tag || "element"}${item.text ? ` "${String(item.text).slice(0, 24)}"` : ""}`).join("; "), expiredShare) : "";
  const room = max - head.length - [notes, stale].filter(Boolean).reduce((sum, part) => sum + part.length + 3, 0) - 3;
  let picked = "";
  if (active.length) {
    const label = `selected ${active.length}: `;
    const parts = [];
    for (const item of active) {
      const where = item.vsrc || (item.vgen ? `{{${item.vgen}}}` : item.selector || "");
      const text = item.text ? ` "${String(item.text).slice(0, 30)}"` : "";
      const part = `${item.tag || "element"}${text}${where ? ` ${where}` : ""}${item.same_vsrc_count > 1 ? ` x${item.same_vsrc_count}` : ""}`;
      const rest = active.length - parts.length - 1;
      const tail = rest ? `; +${rest} more` : "";
      if ((label + [...parts, part].join("; ") + tail).length > room) break;
      parts.push(part);
    }
    const left = active.length - parts.length;
    picked = clip(label + parts.join("; ") + (left ? `${parts.length ? "; " : ""}+${left} more` : ""), Math.max(room, 0));
  } else if (gone.length) picked = "selected 0";
  const summary = [head, picked, stale, notes].filter(Boolean).join(" · ");
  return { view: "canvas", focus: { kind: "app_project", id: project.id, label: project.name }, summary: clip(summary, max) };
}

/** Fold older unattributed snapshots in the newest-first history, keeping the current save and recorded steps. */
export function partitionLegacyHistory(entries, currentRevision) {
  const currentIndex = entries.findIndex((entry) => entry.revision === currentRevision);
  const recordedEntries = [];
  const previous = [];
  entries.forEach((entry, index) => {
    if (currentIndex >= 0 && index > currentIndex && !entry.author?.kind
      && (!entry.action || entry.action === "legacy")) {
      previous.push(entry);
    } else {
      recordedEntries.push(entry);
    }
  });
  return { recordedEntries, previous };
}
