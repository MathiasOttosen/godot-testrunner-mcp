---
name: pixel-diff
description: Visual regression workflow for godot-mcp. Use after renderer or UI changes to compare screenshots, inspect diff images, and update baselines only when intended.
argument-hint: [approve:<name>[,<name>...] | approve:all]
allowed-tools: [Read, Glob, Grep, Bash, mcp__godot_mcp__start_ui_session, mcp__godot_mcp__compare_ui_screenshot, mcp__godot_mcp__update_baseline, mcp__godot_mcp__screenshot_ui]
---

# pixel-diff

Use this workflow after any renderer, scene, or UI change that could alter visible output.

## Arguments

The user invoked this with: $ARGUMENTS

Parse optional approval flags:

- `approve:<name>[,<name>...]` pre-approves only the listed baselines.
- `approve:all` pre-approves every diff update for this run.

Warn in your report when `approve:all` is used. It can silently accept unintended visual changes.

## Flow

1. Ensure the relevant UI state is open. Start a UI session if needed, then navigate to the exact screen state being verified.
2. Call `compare_ui_screenshot(baseline_name, threshold=0.02)`.
3. Inspect the returned JSON:
   - If `passed` is `true`, report the baseline name and `diff_ratio`, then continue.
   - If `error` is `baseline_not_found`, treat it as a first capture and move to baseline creation.
   - If `passed` is `false`, inspect the diff image and describe what visibly changed.
4. On failure:
   - If the baseline is not pre-approved, stop and ask whether to update the baseline or adjust the code.
   - If the baseline is pre-approved, call `update_baseline(baseline_name)` and report that the update was automatic.
5. On first capture:
   - Call `update_baseline(baseline_name)`.
   - Report that an initial baseline was created.

## Reporting

Always include:

- Baseline name
- `diff_ratio` when available
- Diff image path on failures
- Whether a baseline update was user-approved, pre-approved, or a first capture

## Baselines

- Baselines live in `tests/ui_screenshots/<name>.png`.
- Diff images live in `tests/ui_screenshots/diffs/<name>_diff.png`.
- Baseline names should be simple identifiers like `t0_room`, `journal_open`, or `night_end_overlay`.

## Safety

- Do not update a baseline on an unexpected diff unless the user approved it or the invocation explicitly pre-approved it.
- `update_baseline` stages the baseline file but does not commit it. Keep the baseline change visible in git history with the normal task commit.
