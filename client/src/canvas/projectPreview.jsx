import React, { useCallback, useMemo, useRef, useState } from "react";
import { useProjectCanvas } from "../pages/projectCanvas.js";
import { useProjectLivePreview } from "../pages/projectLivePreview.js";
import { usePreviewEdits } from "../preview-edits.js";

/**
 * The project preview shared by the Applications and Canvas screens: one frame reference, the live refresh
 * (`useProjectLivePreview`), the second Dock frame bridge (`useProjectCanvas`) and the in-place edits of the handles
 * (`usePreviewEdits`). Both screens use this hook, so the preview, its refresh, its edits and the agent tools that
 * reach it behave the same in both places.
 */
export function useProjectPreviewCanvas({ projectId, preview, baseline, lang, onRevision, onError }) {
  const frameRef = useRef(null);
  // The frame mounts a render after the preview starts; the bridge must greet that element, so it follows it.
  const [frameElement, setFrameElement] = useState(null);
  const attachFrame = useCallback((node) => { frameRef.current = node; if (node) setFrameElement(node); }, []);
  const mountedFrame = useMemo(() => ({ current: frameElement }), [frameElement]);
  const frames = useProjectLivePreview(projectId, preview, baseline, frameRef, onRevision, onError);
  const visible = frames[0] || preview;
  usePreviewEdits(projectId, visible?.state === "running", frameRef, lang);
  useProjectCanvas(mountedFrame, projectId, visible?.state === "running" ? visible.url : null, visible?.revision, lang);
  return { frameRef, attachFrame, frames, visible };
}

/**
 * The preview frames. During a refresh the next page loads hidden on top of the visible one, so there can be two.
 * `height` is any CSS height; the visible frame gets `frameRef` (pass `attachFrame` from the hook).
 */
/** Permissions the preview frame may use: the microphone only for projects that carry the transfer assistant. */
export function previewAllow(project) {
  return project && Object.hasOwn(project.files || {}, "assets/transfer-assistant/assistant.js") ? "microphone 'src'" : undefined;
}

export function PreviewFrames({ frames, frameRef, title, height = 560, allow }) {
  return <div className="relative" style={{ height }}>
    {frames.map(({ key, src, pending, onLoad }) => <iframe key={key} ref={pending ? null : frameRef}
      title={title} src={src} onLoad={onLoad}
      referrerPolicy="origin" allow={allow} aria-hidden={pending || undefined} tabIndex={pending ? -1 : undefined}
      className="w-full border rounded-md" style={{ height: "100%", borderColor: "var(--line)", background: "white",
        ...(pending ? { position: "absolute", inset: 0, opacity: 0, pointerEvents: "none" } : {}) }} />)}
  </div>;
}
