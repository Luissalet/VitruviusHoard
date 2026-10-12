import { changedFields } from "./copilot-core.js";

export function settingsForm(settings = {}) {
  return {
    backendText: JSON.stringify(settings.backend || {}, null, 2),
    widthsText: (settings.widths || [390, 1024, 1440]).join(", "),
    videoEnabled: settings.video_enabled !== false,
    visionEnabled: settings.vision_enabled !== false,
  };
}

export function settingsPatch(baseline, draft) {
  const changes = changedFields(baseline, draft);
  const patch = {};
  if ("backendText" in changes) patch.backend = JSON.parse(changes.backendText || "{}");
  if ("widthsText" in changes) {
    const widths = changes.widthsText.split(",").map((s) => Number(s.trim())).filter((n) => Number.isFinite(n) && n > 0);
    if (widths.length) patch.widths = widths;
  }
  if ("videoEnabled" in changes) patch.video_enabled = changes.videoEnabled;
  if ("visionEnabled" in changes) patch.vision_enabled = changes.visionEnabled;
  return patch;
}

export const mergeSettingsForm = (baseline, draft, settings) => ({ ...settingsForm(settings), ...changedFields(baseline, draft) });
