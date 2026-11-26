import React, { useRef } from "react";
import { useProjectCanvas } from "../pages/projectCanvas.js";
import { useProjectLivePreview } from "../pages/projectLivePreview.js";

/**
 * The project preview shared by the Applications and Canvas screens: one frame reference, the live refresh
 * (`useProjectLivePreview`) and the second Dock frame bridge (`useProjectCanvas`). Both screens use this hook, so the
 * preview, its refresh and the agent tools that reach it behave the same in both places.
 */
export function useProjectPreviewCanvas({ projectId, preview, baseline, lang, onRevision, onError }) {
  const frameRef = useRef(null);
  const frames = useProjectLivePreview(projectId, preview, baseline, frameRef, onRevision, onError);
  const visible = frames[0] || preview;
  useProjectCanvas(frameRef, projectId, visible?.state === "running" ? visible.url : null, visible?.revision, lang);
  return { frameRef, frames, visible };
}

/**
 * The preview frames. During a refresh the next page loads hidden on top of the visible one, so there can be two.
 * `height` is any CSS height; the visible frame gets `frameRef`.
 */
export function PreviewFrames({ frames, frameRef, title, height = 560 }) {
  return <div className="relative" style={{ height }}>
    {frames.map(({ key, src, pending, onLoad }) => <iframe key={key} ref={pending ? null : frameRef}
      title={title} src={src} onLoad={onLoad}
      referrerPolicy="origin" aria-hidden={pending || undefined} tabIndex={pending ? -1 : undefined}
      className="w-full border rounded-md" style={{ height: "100%", borderColor: "var(--line)", background: "white",
        ...(pending ? { position: "absolute", inset: 0, opacity: 0, pointerEvents: "none" } : {}) }} />)}
  </div>;
}
