import test from "node:test";
import assert from "node:assert/strict";
import { settingsForm, settingsPatch, mergeSettingsForm } from "./src/settings-draft.js";

test("refresh merges changed widths with a native edit in another settings field", () => {
  const original = settingsForm({ widths: [390], video_enabled: true });
  const draft = { ...original, widthsText: "420, 1440" };
  const server = { widths: [390], video_enabled: false };
  const merged = mergeSettingsForm(original, draft, server);
  assert.deepEqual(settingsPatch(settingsForm(server), merged), { widths: [420, 1440] });
  assert.equal(merged.videoEnabled, false);
});

test("an edit typed during Save remains a separate patch after acknowledgement", () => {
  const submitted = settingsForm({ widths: [420], video_enabled: true });
  const current = { ...submitted, widthsText: "640", visionEnabled: false };
  const response = { widths: [420], video_enabled: false };
  const merged = mergeSettingsForm(submitted, current, response);
  assert.deepEqual(settingsPatch(settingsForm(response), merged), { widths: [640], vision_enabled: false });
  assert.equal(merged.videoEnabled, false);
});
