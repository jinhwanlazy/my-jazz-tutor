# Workflow development

[English](README.md) · [Korean original](README.ko.md)

This is the workflow development area of the `my-jazz-tutor/` monorepo. Sessions
opened here edit coaching rules, curriculum, and software. Daily practice belongs
in `../practice`; both areas share the root Git repository.

## Development and publishing

Run development commands from this directory unless stated otherwise:

```sh
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python review.py validate-curriculum
uv run python review.py status
```

`status` and `validate` only read actual records. Development assignments and
reports must use temporary test directories. Write development reports elsewhere:

```sh
uv run python review.py report --output build/preview.html
```

Source edits do not immediately affect practice. After a release, any change to
code, curriculum, or COACH requires a new version in both `curriculum.yaml` and
`pyproject.toml`, followed by `uv lock` and tests. Historical tasks are evaluated
against their assigned criteria. Current milestones count only successes with
compatible criteria, material, and playing conditions.

Commit validated source and create a version tag before publishing. This example
selects `v0.2.9`; create a new tag for later releases instead of moving an old tag:

```sh
uv run python publish.py --ref v0.2.9
```

Version history lives in Git commits and tags. Files from the chosen commit's
`workflow/` directory are cached in `../practice/.runtime/<commit>/`, outside Git
tracking. Publication activates the selected commit by default, pinning its full
hash in local `practice/runtime.json`. `--activate` remains supported; use
`--cache-only` to prepare a cache without changing the pin or tasks.

Compatible unfinished tasks carry forward with their original snapshots. Tasks
whose exercise, key, assigned BPM, playing conditions, material, criteria, or
instructions are no longer supported are retired with an update reason. Retirement
preserves records and MIDI, adds no performance result or prerequisite credit, and
does not defer the replacement exercise as a same-day skip. Version numbers and
UI/accompaniment changes alone do not retire tasks. Completed reports remain intact.

The default ref is `HEAD`; publication rejects uncommitted runtime source changes.
An explicit older tag installs that committed version independently of the working
source. `practice/runtime-ref` is the first-run default for new workspaces.
Updating the launcher default does not change an existing local pin. Deleting the
cache restores the same commit on next launch. If that commit is missing from
local Git history, startup stops instead of substituting development source.

Old `practice/releases/` copies remain in Git history. To migrate an old install
without changing its runtime, select a commit whose runtime files match it exactly.
`active-version` remains a local legacy compatibility marker; `runtime.json` is
the active selector.

Python dependencies are locked in `uv.lock`; runtime hashes are checked on launch.
Personal CSV records, profiles, MIDI, feedback notes, reports, and backups remain
untracked. After cloning, follow [practice setup](../practice/README.md) before
installing the launcher or publishing. Never copy actual practice data into shared
tests.

## Web practice room

Runtime 0.2.0 introduced browser-based assignments, practice, result entry,
rule-based feedback, history, and corrections. It uses a Python standard-library
server and Web Audio, with no external LLM API key or Node runtime. Conversational
AI coaching and musical MIDI analysis are outside the web interface's current scope.
The interface defaults to English. **Settings → Display language** switches between
English and Korean and remembers the choice in this browser at the same address
and port. Switching preserves active capture and unfinished report inputs. Agents
follow the user's conversation language independently. Original notes and historical
evidence retain their original wording.

Choose one label after practicing: 😈 **Impossible**, 💪 **Challenging**,
🙂 **Good practice**, or 🙄 **Too easy to be useful**. One tap saves it.
**Add a note · optional** is the only text field; you can edit the label or memo
later. Date, duration, and metronome settings are recorded automatically.
Good/too-easy feedback can open the next practice exercise in the same key without
claiming correct notes, steady timing, mastery, or retention. No accuracy survey
or missing-evidence prompts are required to continue.

Once a web-capable version is active, run this from the repository root. `uv`
prepares the environment; `jazz` with no arguments runs `serve --open`:

```sh
uv run --project practice jazz
```

The server listens at `http://127.0.0.1:8765` and cannot be reached from other
devices. Use `--port 8768` if needed, and Ctrl+C to stop. After publishing a new
version, restart the server. Unfinished tasks do not block activation. Return with
the same browser, address, and port to recover pending MIDI uploads; recovery also
preserves input attached to retired tasks without creating a performance report.

- **Practice room:** read the task instructions, target conditions, and success
  criteria first, then use the score and its single set of playback controls.
  **Notes and chord progression** expands the written parts. Target BPM and current
  metronome BPM are separate. Adjust tempo beside the score; expand **Sound & MIDI
  settings** for volume, chord pad, and MIDI devices. Click and pad share the same
  beat clock. Resuming starts from the first bar; switching away from the tab
  pauses playback.
- **Score and live input:** a grand staff shows the assigned parts, chord symbols,
  key signature, and rhythm. Blue MIDI marks keep fractional timing against the
  playback clock; their tails show physical key holds, excluding pedal sustain.
  All bars share one continuous horizontal staff and beat scale. **Follow playback**
  scrolls within the score as the cursor advances, without jumps at bar boundaries
  or page turns. A score that fits the viewport stays still; the cursor returns to
  the beginning at each loop. Turn following off to scroll manually. Whole-note
  centers are transparent, and the score omits bar numbers and hand labels.
  Improvisation has allowed pitches and rest bars, with no invented melody; bass
  diamonds mean a beat-1 attack whose
  hold length is unspecified. Input placement follows the assigned staff or pitch
  range, not detected hands. This view does not assess correctness or fill reports.
  Charleston eighth notes illustrate short attacks on 1 and 2&; the illustration
  does not add an exact hold-duration requirement to the assignment.
- **Finish and record:** finishing saves input and opens four feedback labels.
  Tap one to save, optionally add a memo, then choose **Next practice**. Impossible
  suggests a slower tempo; challenging keeps the same tempo. Good/too-easy feedback
  prioritizes the next eligible exercise. If all are comfortable, too-easy raises
  the tempo within the curriculum's limits. These choices do not pass mastery criteria.
- **Skip:** defer an unattempted task for today with a reason. The next task still
  follows prerequisites. There is no daily task-count limit.
- **History and progress:** filter by date, exercise, and key; compare original
  notes and assigned versus actual conditions. Corrections preserve earlier
  reports. Download raw MIDI and session metadata here.

MIDI is optional. In a browser supporting Web MIDI on a local address, choose
**MIDI input → Connect** and grant permission. All connected inputs are selected
by default; you can choose a particular device. The browser's raw bytes are saved
without requesting SysEx permission. Other practice features work without MIDI
access or a device. See [MDN Web MIDI](https://developer.mozilla.org/en-US/docs/Web/API/Web_MIDI_API)
for browser support details.

Automatic observations have specific meanings:

- **BPM** is the metronome setting at the last note input, or the last playback
  setting when there is no MIDI. It is not an analysis of your playing tempo.
- **MIDI span** runs from the first Note On through the final Note Off or sustain
  release. Only leading and trailing inactivity is excluded; internal rests stay.
  Raw input is never trimmed. Missing note endings, device changes, or interrupted
  capture leave the span unknown.
- If a MIDI span cannot be measured, **playback time** excluding pauses is used
  for normally finished sessions. Interrupted sessions leave total time unknown.
  Preparation and reflection outside playback are not added automatically.
- **Practice date** uses the session's first input (or start without input) in the
  profile's timezone, defaulting to UTC. A session crossing midnight belongs to
  that starting day. For sessions on multiple days, the report uses the latest day
  and the daily totals allocate each session to its own day. With no saved session,
  the feedback date is labeled as the recording date; tempo and duration stay unknown.

Every three seconds, input is first saved to IndexedDB and then sent to the
server. Chunks remain in the browser until acknowledged; retries do not duplicate
them. After reconnecting, choose **Recover practice** to send pending input.
Return using the original browser, address, and port so the same IndexedDB is
available. Close other practice tabs before recovery. Input after the last
checkpoint may be lost if the browser is forcibly closed. Clearing browser storage
also removes unsent chunks.

Development previews cannot point at production practice data. From this directory:

```sh
mkdir -p build/web-preview
uv run python review.py --practice-root build/web-preview serve --open --port 8768
```

Preview records stay in the ignored `build/web-preview/` directory.

### Managing the uv launcher

`launcher/` is the source of the practice uv project and entry point. Apply changes
from this directory:

```sh
uv lock --project launcher
uv run python install_launcher.py
```

Installation updates `practice/pyproject.toml`, `practice/uv.lock`,
`practice/src/jazz_practice/`, `practice/jazz`, and `practice/runtime-ref`. The
launcher verifies the pinned cache against Git and runs it with its dependencies.
Existing CLI commands work through `uv run --project practice jazz status` from
the repository root. `uv run --project practice jazz runtime` shows the version,
commit, and cache. Launcher versions are separate from runtime/curriculum versions;
installation preserves actual records and the local `runtime.json` pin. Project
scripts follow the [uv documentation](https://docs.astral.sh/uv/concepts/projects/config/#command-line-interfaces).

## MIDI storage and exports

`practice/sessions.sqlite3` stores raw input and playback events. The CSV contains
final self-reports, linked to sessions by `task_id`. Ending a recording does not
submit a practice report.

Git does not preserve personal records. Stop the server before backing up the CSV,
SQLite database, profile, feedback notes, and `runtime.json` together to a private
location. The cache can be rebuilt, but retain the pinned commit in Git history.
Use `git bundle create <private-backup-path> --all` to back up repository history.
The ignored `practice/backups/` directory is not a substitute for a backup on a
separate device.

Downloaded `.jpm` files are minimal raw archives, not standard `.mid` files. After
the four-byte `JPM1` header, frames repeat in this little-endian format:

| Field | Format | Meaning |
| --- | --- | --- |
| at_ms | float64 | Receipt time in milliseconds since session start |
| port | uint16 | Input-device number within the session |
| length | uint16 | Byte count of the next MIDI message |
| data | length bytes | Original MIDI message bytes |

The companion `.json` contains assigned conditions, device information, playback,
pause and tempo application times, pad use, and derived measurements. Corrections
and duration adjustments never change raw input. This format preserves input for
future analysis; it does not define analysis rules or scores.

## Web validation

```sh
uv run python -m unittest discover -s tests -v
uv run python review.py validate-curriculum
node --test tests/capture.test.mjs tests/i18n.test.mjs tests/score.test.mjs
```

Optional browser integration checks use Playwright. The script creates and cleans
up a temporary workspace and server without using actual practice records:

```sh
npm install --prefix build/browser-tools playwright
PLAYWRIGHT_MODULE="$PWD/build/browser-tools/node_modules/playwright/index.mjs" \
CHROME_EXECUTABLE=/usr/bin/google-chrome node tests/browser.mjs
```

Screenshots go to `build/browser/`. Checks cover MIDI permission denial, synthetic
input preservation and timing, tempo/pad playback, reports, corrections, skips,
offline recovery, and mobile layout. Synthetic MIDI tests do not verify a physical
keyboard connection or speaker quality.

## Assignment and reporting CLI

Several tasks can be practiced sequentially in one day, with only one pending
assignment at a time. Report or cancel it before assigning another. The default
30 minutes covers the whole day. `status.today` includes reported task count,
known time, reports with unknown duration, and remaining budget. Remaining time is
`null` when a report lacks duration, unless known time already exhausts the budget,
in which case it is zero. The budget never blocks additional practice.

The web labels `impossible`, `challenging`, `good`, and `too_easy` guide practice
choices separately from mastery. Only compatible reports in the same key can open
prerequisites for ordinary practice; review/transfer still require success evidence.
Legacy detailed CLI reports retain their rules: `difficulty: easy` alone does not pass. Unsuccessful tasks reported as `difficulty: hard` and
cancelled tasks are deferred for the same exercise and key that day.
`suggest.deferred_today` preserves original notes and task IDs. Other candidates
must still meet prerequisites. With no candidate, `action: pause` suggests stopping
or simplifying a condition. Deferred tasks return the next day and may be explicitly
retried the same day. A new result takes precedence over an earlier deferral.

Use `cancel` for an unattempted task and `record` if any practice occurred. Preserve
the user's exact reason. Keep criteria, original notes, and assigned conditions;
same-day success is not evidence of later retention or unattempted skills.

Run these from the repository root **only when the user actually starts practice**.
Reading this README does not authorize sample writes to the real log:

```sh
uv run --project practice jazz assign E01 --key C --bpm 60 --reason 'Check the starting point for left-hand roots and pulse'
uv run --project practice jazz record T-ASSIGNED_ID --input /tmp/jazz-result.json
uv run --project practice jazz correct T-ASSIGNED_ID --input /tmp/jazz-corrected-result.json
uv run --project practice jazz cancel T-ASSIGNED_ID --reason 'This task was not practiced'
```

Example result format, not user evidence. Fill only information the user supplied;
omit unknown numbers and checks or leave them `null`:

```json
{
  "practice_date": "YYYY-MM-DD",
  "followed_target": false,
  "actual": {"key": "C", "bpm": 50, "arrangement": "right-melody-only"},
  "checks": {"notes_correct": true, "steady_pulse": null, "no_stops": false},
  "clean_runs": null,
  "actual_minutes": 20,
  "difficulty": "hard",
  "raw_note": "Preserve the user's original note here",
  "hypothesis": "Keep the coach's interpretation separate from reported facts."
}
```

Use `followed_target: true` only when the user explicitly confirms the assigned
conditions. Copying conditions does not automatically mark checks or run counts
as successful. `correct` takes a complete replacement report; the earlier event
remains in the CSV.

## CSV structure

Append events only to `practice/practice.csv`. `task_id` links assignments and
results; `event_id` identifies each event. Writes use a file lock.

| Main column | Meaning |
| --- | --- |
| event_type | assigned / reported / cancelled / retired / corrected |
| target_json | Assigned key, BPM, hands, rhythm, bass, voicing, melody, material, and criteria |
| actual_json | Conditions the user reports actually practicing |
| checks_json | Notes, pulse, and uninterrupted playing: true / false / null |
| clean_runs | Consecutive successful runs under the conditions; empty when unknown |
| raw_note | Original user text, including commas and newlines; optional with a web label |
| difficulty | Web labels: impossible / challenging / good / too_easy; legacy CLI values retained |
| reason | Assignment/closure reason; web reports store a session-reflection-v1 JSON timing snapshot |
| hypothesis | Coach interpretation, separate from the original note |
| supersedes | ID of the previous result replaced by a correction |

Scripts calculate metrics. The LLM must not store invented overall ability scores.
Reports do not alter evidence and can be deleted and regenerated.
