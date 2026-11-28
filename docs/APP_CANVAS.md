# App preview canvas

In **Applications**, choose **Open in Canvas** to select the project on the Canvas. Entering Canvas from the sidebar
selects the last active project created or opened in this browser. Use the project picker to switch or clear the selection.
Choose **Open preview** to start the preview in either view. The preview runs on its own loopback origin and keeps the same address when the project switches revisions. Links, stylesheets and record actions use the project's own routes. Opening the preview in another tab is still available.

- `app_project_canvas_view(id, scope?, max_chars?, actor?)` reads the displayed page or current viewport and returns control references.
- `app_project_canvas_act(id, action, args, actor?, target?)` supports `click`, `fill`, `select`, `navigate`, `scroll`, `highlight` and `wait`. It uses the App Dock arguments for that action. Send `actor: {id, name, color}` to identify the cursor. To point out part of a page, call `highlight` with a `ref` or `text` and an optional `note`.
- For `click`, `fill` and `select`, the cursor travels to the control and pulses before the action. The control is outlined after the action. Each actor's cursor starts from its last position in the preview. Agent scrolling and highlighting carry the cursor to the destination. The label and note move outside the target wherever there is space. Use `args.ref`, `args.text` or `args.label` to locate it. You can also supply `target` with a CSS `selector` or a `vsrc` from the current preview. A document-relative `box` with `x`, `y`, `w` and `h` can distinguish repeated source positions. Reduced motion places the cursor directly at its destination and retains the outline. The edit cue fades after four seconds of inactivity and keeps its position for the next action.
- The app uses the same cursor for reads, actions and source edits. When a call identifies the caller, the project remembers the caller's explicit actor for later calls. The caller ID supplies the default name and a stable color. Each caller without a declared color gets an unused color in the project while the palette has room. An explicit name or color carries through to the next edit even when it omits actor. Both tools need one Applications tab hosting the project's preview. They report when it is absent or when multiple tabs are hosting it. Preview actions go through the project's own controls. Source revisions and `app_project_undo` are managed by the [application project workflow](APP_PROJECTS.md).

The dedicated **Canvas** places Navigate, Select and Comment together in its toolbar. The conversation rail is available as soon as a project is open. It places the person's submitted request and the agent's visible replies beside the preview. The native copilot supplies the text of requests and replies, and the embedded transfer assistant supplies its transcribed request and response through the validated preview bridge. Clicks, scrolling and navigation from the cursor's event stream stay available in collapsed groups. Committed source steps come from revision history with their author, target and files. The history and live edit activity show up to three library references by name, and the `+N` control reveals the rest. Lint findings appear on a separate line. Older history entries resolve from their saved IDs. Project read and edit responses retain those IDs and include a bilingual `materials` view with `references` and `warnings`. The rail can be collapsed independently of Focus mode, which folds the navigation while keeping its icon links available. Opening comment mode reveals the rail and resizes the existing preview continuously. With reduced motion, the layout changes immediately. Elements in the inspector select and bring into view the corresponding node from the active document. Alt+Shift+S and Alt+Shift+C switch modes, and the toolbar and element list also support arrow keys, Home and End. Comments keep their original reference. A pin with a unique ID or data-vid follows text edits if its tag and source file still match. The preview marks an anchor lost after checking the current revision. The person can resolve, reopen or undo comments. The source history shows each recorded transition, author and time. Edits made through the agent API use the caller's identity when present and show Agent when it is unavailable. Edits made in the workbench or Canvas show Person. Saved authors on existing steps are retained. An edit with several changed files shows the total in the active language, with the paths in the item's tooltip. Undo checks that the current revision and its update timestamp still match. The last undo result follows the active interface language. The latest-change control restores the preceding saved source. Undo on an individual history step reverses that edit while leaving other files intact. An undone step stays in the history with an Undone label. Redo restores the source immediately before the most recent undo while that undo is still the latest change. It reports a conflict if a later edit would be overwritten in a file touched by the selected step. The history groups older unattributed revisions in one expandable row and keeps the current revision visible. The person can explicitly restore the prior saved version. Element labels in the layer list stay on one line and expose their full text in the tooltip. Selected cards show the localized element type and its name. Technical details reveal the selector, source path and generated origin when available. The agent still receives the original selection fields. In-place updates keep the preview document open when its source change can be safely patched. Other source changes load the replacement frame before switching to it.

Requests and replies use the rail's full text area. Live actions scroll in a fixed area below them, so clicks
and scrolling in the preview leave the history in place.
While connecting to the preview, the mode toolbar shows that it is waiting for the inspector. A request for Select
or Comment stays pending and starts when the inspector answers. Navigate and Escape cancel the pending request.
Canvas holds the first click until the preview confirms the mode.
The click then selects or anchors the element without activating its link or form.
The host waits for the preview document before sending its greeting to the preview's origin.
The preview proxy loads the inspector before project scripts so its window capture handles subsequent clicks
in Select and Comment as well. In Navigate, the page handles its own input.
Picking an element in Comment mode brings the whole form into view and focuses the note field. A saved comment
quotes the text of its anchor on the displayed page. When it changes, **Text when commented** contains the
original quote and crop. The preview's edit confirmation and text
editor use the same theme. The outline label uses the same type and name as the selection card,
with selectors and source paths available under Technical details. It uses a free area near the element, clear of text,
controls and edit handles. If only a shorter label fits, it shows the element type. In a fully occupied
preview, the outline and the name in the selection card remain available.
Inline text edits save when the field loses focus, when you click outside it, or when you press Enter.
Double-clicking a text node bound entirely to `{{name}}` or `{{description}}` edits the corresponding project field.
The editor identifies the field and says the value is shared across the application. Those edits keep the template
bindings in the source and can be undone from History.
Escape cancels the draft. Edits that affect several rendered elements still ask for confirmation.
Navigate clears the active selection from the sidebar, preview outline and agent context. Returning to Select
restores the last selection on that page. Picking an element from the list starts a new selection.
When an edit or undo updates the open preview, the selected cards reflect the newly displayed revision.
The edit handles show the nearest whole pixel
while applying and saving the precise value.
History and comments show the readable element name. Selectors, source locators and file lists are available
under **Technical details**. Older history entries without a saved name still retain their locators there.
A comment follows its anchor's name in the visible revision. If the name changes,
**Text when commented** keeps the original name and any saved crop.
The Canvas header names the source revision in the preview. History numbers each action and labels the revision
shown in the preview separately. Restoring a snapshot adds a step and keeps that snapshot's revision number.
Resolving a pending comment as an agent records its acknowledgement and resolution together. Undo on the comment
restores the previous pending state. Undoing the source edit that resolved a comment reopens the comment and keeps
its previous summary visible. The agent
can name the exact revision of the fix, including a change in another file. Without an explicit revision the
comment follows an unambiguous edit at its anchor or in the anchored file. Closing a comment by hand does not
link it to a source edit.

Vitruvius owns the reverse proxy and starts a separate copy of the source runtime for each displayed revision. The current runtime stays available until its successor is ready. The proxy adds the shared App Dock bridge and any installed scripts listed in `app_preview.PREVIEW_SCRIPTS` to HTML. A response exposes its actual revision through `X-Vitruvius-Revision` and the `vitruvius-preview-revision` meta tag. It also names the opening of the preview (one per proxy, unchanged by revision refreshes) through `X-Vitruvius-Session` and `vitruvius-preview-session` meta tag; `app_project_preview` status carries it as `session`. The script list affects served previews. The source files, standalone runtime and export ZIP preserve the project's own content.

The current styles stay active until all replacement sheets are ready, including when a save edits the page and its stylesheets together. A failed stylesheet keeps the previous preview visible and reports the refresh error.

When Vitruvius is docked, the outer App Dock continues to address the Vitruvius page. **Applications** hosts the preview in an inner frame with `referrerPolicy="origin"`. The inner handshake and calls use the existing `dock/hello`, `dock/ready`, `dock/call` and `dock/result` messages. Each host checks its own frame's window and origin. A project-specific event stream connects the Applications page to the canvas tools without opening a tab.

The browser includes its displayed revision in the canvas stream request. This gives consecutive agent edits a short window to let the previous revision reach the visible frame. The inner host relays `canvas/presence {id, actor, revision, target, expires_at}` for source edits on the same stream as tool calls. The preview checks its served revision before using the target's `vsrc`, `selector`, inferred `sources` or `box`. It measures the element in the live document when it can resolve one. It acknowledges through `dock/result` after the pulse starts, or immediately when reduced motion is enabled. The committed revision still arrives on the revision stream. A mutating `dock/call` may carry `presence` with locator hints for the same cursor and outline behavior.
