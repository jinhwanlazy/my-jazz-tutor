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
selects `v0.2.4`; create a new tag for later releases instead of moving an old tag:

```sh
uv run python publish.py --ref v0.2.4 --activate
```

Version history lives in Git commits and tags. Files from the chosen commit's
`workflow/` directory are cached in `../practice/.runtime/<commit>/`, outside Git
tracking. `--activate` pins the full commit hash in local `practice/runtime.json`.
An unfinished task blocks activation of a different commit. Omitting `--activate`
only prepares the cache.

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
The interface uses English; agents follow the user's language. Original user notes
and historical evidence retain their original wording.

Once a web-capable version is active, run this from the repository root. `uv`
prepares the environment; `jazz` with no arguments runs `serve --open`:

```sh
uv run --project practice jazz
```

The server listens at `http://127.0.0.1:8765` and cannot be reached from other
devices. Use `--port 8768` if needed, and Ctrl+C to stop. If an unfinished task
blocks activation, record its actual result with the old runtime, or cancel it
only when the user confirms they did not practice. Then run
`uv run python publish.py --ref v0.2.4 --activate` from this directory. Never invent
or delete practice evidence just to install the UI.

- **Practice room:** start a suggested or selected task. Target BPM and current
  metronome BPM are separate. Adjust tempo and volume, and optionally enable the
  chord pad. Both share the same beat clock. Resuming starts from the first bar;
  switching away from the tab pauses playback.
- **Finish and record:** finishing saves input and suggests BPM and duration.
  Confirm the key, hands, section, notes, pulse, stops, successful runs, and note
  yourself. An easy difficulty rating alone is not a pass. Record what actually
  happened before moving on from a difficult task.
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

Suggested values have specific meanings:

- **BPM** is the metronome setting at the last note input, or the last playback
  setting when there is no MIDI. It is not an analysis of your playing tempo.
- **MIDI span** runs from the first Note On through the final Note Off or sustain
  release. Only leading and trailing inactivity is excluded; internal rests stay.
  Raw input is never trimmed. Missing note endings, device changes, or interrupted
  capture leave the span unknown.
- If a MIDI span cannot be measured, **playback time** excluding pauses is
  suggested. Enter duration manually for recovered interrupted sessions. Review
  the actual time and include preparation or reflection if appropriate.

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
node --test tests/capture.test.mjs
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

For an easy task, briefly verify the criteria before continuing; `difficulty: easy`
alone does not pass it. Unsuccessful tasks reported as `difficulty: hard` and
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
| event_type | assigned / reported / cancelled / corrected |
| target_json | Assigned key, BPM, hands, rhythm, bass, voicing, melody, material, and criteria |
| actual_json | Conditions the user reports actually practicing |
| checks_json | Notes, pulse, and uninterrupted playing: true / false / null |
| clean_runs | Consecutive successful runs under the conditions; empty when unknown |
| raw_note | Original user text, including commas and newlines |
| hypothesis | Coach interpretation, separate from the original note |
| supersedes | ID of the previous result replaced by a correction |

Scripts calculate metrics. The LLM must not store invented overall ability scores.
Reports do not alter evidence and can be deleted and regenerated.
