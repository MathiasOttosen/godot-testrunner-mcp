# Pixel-Diff Visual Regression Design
*2026-04-14 · The Artifact Room*

## Problem

Visual bugs (wrong curve geometry, incorrect rendering at non-default strength) slip through AI-assisted development because agents cannot see rendered output. Validation criteria exist in natural language but have no runnable check. Screenshots are taken manually and reviewed by humans only.

The result: visual regressions require user intervention to catch, and fixes require user intervention to verify.

## Goal

- Agents automatically compare rendered output against named baselines after any renderer or UI change
- Failing diffs block task completion and surface the diff image + score to the user
- Passing diffs are reported silently and execution continues
- Baseline updates require human approval (or preemptive approval) and are always git-tracked
- Users can pre-approve baseline updates to eliminate repeated interruptions when visual changes are intentional

## Out of Scope

- Cross-machine baseline stability (baselines are machine-specific — same hardware, same Godot version)
- Animated or particle-driven screen regions (no region masking in this version)
- CI/CD integration

---

## Architecture

Two components: an MCP extension and a skill.

- **MCP** owns capability: taking screenshots, running comparison, writing diff images, staging baseline updates
- **Skill** owns policy: when to compare, how to interpret results, baseline update protocol, pre-approval behaviour

---

## MCP Extension — `godot-mcp`

### `compare_ui_screenshot(baseline_name, threshold)`

Compares the current UI session screenshot against a named baseline using `pixelmatch` (pixel-exact).

**Parameters:**
- `baseline_name: string` — filename without extension, e.g. `t0_room`. Resolved to `tests/ui_screenshots/<name>.png`
- `threshold: float` — max acceptable changed-pixel ratio, default `0.02` (2%)

**Returns:**
```json
{
  "passed": true,
  "diff_ratio": 0.008,
  "diff_image_path": "tests/ui_screenshots/diffs/t0_room_diff.png",
  "baseline_path": "tests/ui_screenshots/t0_room.png"
}
```

**Behaviour:**
- Always writes the diff image to `tests/ui_screenshots/diffs/<baseline_name>_diff.png` regardless of pass/fail
- If baseline file does not exist, returns `{ "error": "baseline_not_found", "baseline_name": "..." }`
- Uses `pixelmatch` for comparison — pixel-exact, no perceptual tolerance

**Why pixel-exact:** Godot's renderer is deterministic on the same hardware. Sub-pixel tolerance (SSIM) adds complexity without benefit for this use case.

---

### `update_baseline(baseline_name)`

Promotes the most recent screenshot to the named baseline slot.

**Behaviour:**
- Copies the screenshot captured in the current UI session to `tests/ui_screenshots/<baseline_name>.png`
- Runs `git add tests/ui_screenshots/<baseline_name>.png`
- Does **not** commit — the agent commits as part of its normal workflow, keeping the update visible in `git diff` and the commit message
- Returns `{ "updated": true, "path": "tests/ui_screenshots/<baseline_name>.png" }`

---

## `pixel-diff` Skill

### Invocation

```
/pixel-diff [approve:<name>[,<name>...] | approve:all]
```

The optional `approve` parameter declares pre-approved baselines for this invocation. Pre-approved baselines update automatically on diff failure without blocking for confirmation.

**Warning embedded in skill:** `approve:all` should only be used when the full scope of visual changes is understood. Unexpected diffs will update silently — the report is the only safeguard.

---

### Flow 1 — Normal (after any renderer or UI change)

1. Ensure a UI session is active (`start_ui_session()` if not already open)
2. Navigate to the relevant screen state
3. Call `compare_ui_screenshot(baseline_name, threshold=0.02)`
4. Read the diff image at `diff_image_path`
5. **If passed:** report `diff_ratio` and `baseline_name` to user, continue task
6. **If failed and baseline not pre-approved:** block; report `diff_ratio`, `diff_image_path`, and a description of what changed visually; wait for user instruction
7. **If failed and baseline pre-approved:** proceed to Flow 2 (update) without waiting

---

### Flow 2 — Intentional update (user approves or baseline is pre-approved)

1. Call `update_baseline(baseline_name)`
2. Report to user: baseline name, old diff_ratio, whether update was pre-approved or user-approved
3. Commit with a message that names the baseline and describes the intentional change
4. Continue task

Commit message format:
```
chore: update baseline <name> — <reason>

Pre-approved / approved by user: <context>
```

---

### Flow 3 — Missing baseline (first capture)

1. `compare_ui_screenshot` returns `error: baseline_not_found`
2. Do not fail — treat as first capture
3. Call `update_baseline(baseline_name)`
4. Report to user: "No baseline existed for `<name>` — captured initial reference"
5. Commit the new baseline file

---

## Baseline Naming Convention

Baselines are named after the game state they represent, matching the existing files in `tests/ui_screenshots/`:

| Name | State |
|------|-------|
| `t0_room` | Room at Time T0 |
| `t1_room` | Room at Time T1 |
| `journal_open` | Journal visible |
| `night_end_overlay` | Night end overlay |

New baselines follow the same pattern: `<context>_<state>`.

---

## Baseline Integrity

- All baseline PNGs live in `tests/ui_screenshots/` and are git-tracked
- `update_baseline` stages but never commits — the commit is always explicit and authored by the agent with a descriptive message
- Rollback: `git checkout tests/ui_screenshots/<name>.png`
- Diff images in `tests/ui_screenshots/diffs/` are gitignored (ephemeral, regenerated on each run) — requires a `tests/ui_screenshots/diffs/.gitignore` entry (`*` + `!.gitignore`)

---

## Meta Context

This design is part of a broader pattern: visual correctness should be either (a) pushed down to math that can be asserted in headless tests, or (b) verified by a tool that closes the human-review loop automatically.

The renderer math extraction (Commit 1 of the integration testing plan) is approach (a). This pixel-diff system is approach (b). Together they cover the two classes of visual bug that slipped through manual review.
