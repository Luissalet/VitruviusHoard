# Application critique loop

Open the project's preview in Canvas, go to **Activity** and choose **Assess revision**. The lane shows the best source revision and score, the latest candidate, the changed files, and the criteria that improved or regressed. The capture link opens the assessed candidate, including a candidate whose source has since been replaced by the best revision.

Agents can call `app_project_critique_round` with the application `id` and the current `expected_revision`. The first round can set `tokens_id`. Later rounds reuse that design system. Each round captures the owned preview at 390, 834 and 1440 px and runs deterministic critique. A higher score establishes a new best. A lower score restores the best source and refreshes a running preview. A tie leaves the current candidate active and retains the original best. A concurrent edit or another recorded round returns a conflict so the caller can re-read the project before trying again.

`app_project_critique_loop` reads the best revision, latest evidence and round history. Each comparison identifies the previous best and the source files that differ. Criterion changes include their before and after findings. Source restoration preserves application data and keeps the rejected revisions available in project history. The activity history records source restorations and round undos alongside the individual edit steps. Regular `design_critique` continues to inspect individual captures.

The mutating round call returns an undo receipt for `app_project_critique_round_undo`. It removes the latest recorded round and restores its candidate revision when appropriate, provided that the source and round history still match the receipt. The Canvas lane also offers **Undo round** for rounds started in that lane.
