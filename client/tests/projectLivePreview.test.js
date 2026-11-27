import test from "node:test";
import assert from "node:assert/strict";
import { previewAllow, previewNavigationUrl, refreshKind } from "../src/pages/projectLivePreview.js";

test("iframe microphone permission is limited to the preview origin for both voice assistants", () => {
  for (const marker of ["assets/voice-assistant/microphone.js", "assets/transfer-assistant/assistant.js"]) {
    assert.equal(previewAllow({ files: { [marker]: "" } }), "microphone 'src'");
  }
  assert.equal(previewAllow({ files: { "pages/index.html": "<form></form>" } }), undefined);
  assert.equal(previewAllow({}), undefined);
  assert.equal(previewAllow(null), undefined);
});

test("only compatible page and sheet changes can patch the loaded document", () => {
  const event = { previous_revision: "a", revision: "b" };
  for (const [files, expected] of [
    [["pages/index.html", "pages/records/[id].html"], "html"],
    [["assets/page.css"], "css"],
    [["layout.html"], "full"],
    [["assets/client.js"], "full"],
    [["pages/index.html", "assets/page.css"], "full"],
    [[], "full"],
  ]) assert.equal(refreshKind({ ...event, files }, "a", "b"), expected);
  assert.equal(refreshKind({ ...event, files: ["assets/style.css"], global_styles: ["assets/style.css"] }, "a", "b"), "full");
  assert.equal(refreshKind({ ...event, files: ["pages/index.html"] }, "older", "b"), "full");
  assert.equal(refreshKind({ ...event, files: ["pages/index.html"] }, "a", "newer"), "full");
});

test("preview navigation retains path, query and fragment on the owned origin", () => {
  globalThis.window = { location: { href: "http://127.0.0.1:59999/design/" } };
  const url = "http://127.0.0.1:59998/";
  assert.equal(previewNavigationUrl(url, "/records?q=map#form"), url + "records?q=map#form");
  assert.equal(previewNavigationUrl(url, "//example.test/"), url);
  assert.equal(previewNavigationUrl(url, "/\\example.test/"), url);
});
