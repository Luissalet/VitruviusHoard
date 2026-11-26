// Pure helpers of the Canvas screen (no DOM or React: they run under `node --test`).

/** The modes of the canvas toolbar, in order. `handles` only shows when the preview says it supports it. */
export const MODES = ["navigate", "select", "comment", "handles"];

/** Messages the inspector inside the preview sends to its host (see `preview-inspector.js`). */
const FROM_PAGE = new Set(["dock/inspector-ready", "dock/select", "dock/comment-target", "dock/comment-anchors", "dock/comment-focus"]);

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

/** `tag.class` of an element. */
export function elementLabel(item) {
  const name = (item?.tag || "element") + (item?.classes?.length ? "." + item.classes.slice(0, 2).join(".") : "");
  const text = item?.text ? ` "${item.text.length > 40 ? item.text.slice(0, 39) + "…" : item.text}"` : "";
  return name + text;
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
