# Daily practice

[English](README.md) · [Korean original](README.ko.md)

This is the daily practice area of the `my-jazz-tutor/` monorepo. Workflow
development belongs in `../workflow`; both areas share the root Git repository.
The commands below run from the repository root.

After cloning, prepare a local profile without overwriting an existing one:

```sh
test -e practice/profile.json || cp practice/profile.example.json practice/profile.json
```

Enter your experience, goals, and time preferences in `practice/profile.json`.
Example values are starting defaults, not evidence about you. Leave unknown
information unset. The coach follows the language you use, unless you request
another language; the example profile does not force a language.

Open this directory as the Codex working directory and say, for example,
`Let's start today's practice.` After playing, describe what happened naturally:
`70 BPM was too difficult, so I played the right hand only at 50 BPM.` The agent
preserves your original note, structures the report, and suggests the next task.

- Default daily budget: **30 minutes** across all tasks, including roughly 5 minutes
  of listening and preparation, 20 minutes of focused work, and 5 minutes of
  recording and reflection. Adjust this in your local profile.
- Tasks may repeat, simplify, check, extend, or review previous work.
- Short original exercises establish a starting point. The coach does not invent
  bars or melodies for a song whose score edition has not been selected.
- Results are based on self-reports. Pitch, swing, and tone are not automatically
  assessed.

```sh
uv run --project practice jazz status
uv run --project practice jazz suggest
uv run --project practice jazz report
```

`practice/reports/index.html` is a read-only progress report. Run `report` again
when it becomes stale. It shows recommendations, evidence, and the distinct states
of unassessed, attempted, successful, and retained on a later day.

With a web-capable runtime (0.2.0 or later) active, one command prepares the
environment, starts the local server, and opens your browser:

```sh
uv run --project practice jazz
```

Choose an exercise and practice with the metronome. Enable the chord pad if you
want accompaniment. A MIDI keyboard can record raw input after you grant access.
When finished, review the suggested BPM and duration, then enter a short report
and note. Feedback compares your report with the criteria; musical MIDI analysis
is not available yet. You can continue through several tasks in one day. History
shows original notes, assigned and actual conditions, corrections, and MIDI exports.

The score shows the assigned right- and left-hand parts with chord symbols. During
playback, a cursor follows the beat and blue marks show MIDI key presses at their
actual positions. Tails show key holds, excluding pedal sustain. Use the playback
buttons beside the score or the metronome controls. Eight-bar exercises have page
arrows; **Follow playback** changes pages and scrolls within the score automatically.
The live view shows the current pass and resets when playback resumes from bar 1.
The original MIDI recording continues independently, including input during pauses.
Input placement does not identify your hands or assess timing accuracy; device
latency can affect alignment. Improvisation tasks show allowed notes and rest bars,
without inventing a required melody.

Choose **Settings → Display language** to switch between English and Korean.
The choice is saved in this browser for the same address and port. Active practice
and unfinished report inputs stay intact when switching languages.

**Assessment pending** means your practice is saved, but some conditions or the
consecutive successful run count are still unknown. Open a history entry to see
what is missing. Use **Correct this report** to add only details you remember;
count complete runs of the assigned section, not individual bars.

The address is `http://127.0.0.1:8765`; stop the server with Ctrl+C. If the port is
busy, use `uv run --project practice jazz serve --open --port 8768`. To start without
opening a browser, use `uv run --project practice jazz serve`. Running `./jazz`
inside this directory also remains supported. Records stay in the existing CSV
and `sessions.sqlite3`. To recover unsent input, return with the same browser,
address, and port, then choose **Recover practice**.

`uv run --project practice jazz runtime` shows the active version, Git commit, and
cache location. First launch resolves `runtime-ref` to a commit in local
`runtime.json`. Later source or tag changes do not change that pin. Deleting the
`.runtime/` cache reconstructs the same commit from local Git history.

Publishing activates the selected release even with unfinished tasks. From the
repository root, run `uv run --project workflow python workflow/publish.py --ref v0.2.8`.
Compatible tasks keep their original conditions; incompatible tasks are retired
with a reason while preserving history and MIDI. Retirement is not a performance
result or a skip. Use `--cache-only` to prepare without activating, and restart the
practice server after activation. Launching alone follows the existing pin.

`practice.csv`, `profile.json`, `workflow-feedback.md`, `sessions.sqlite3`,
`runtime.json`, `active-version`, `.runtime/`, `reports/`, and `backups/` are ignored
by Git. `active-version` is for legacy compatibility; `runtime.json` selects the
active code. The CSV is created when the first task is assigned, and MIDI storage
when the first recording starts. Add local workflow feedback notes as needed.
Missing files mean no data has been recorded; do not fill them with sample results.

Git does not back up personal records. Stop the server, then copy the CSV, SQLite
database, profile, feedback notes, and `runtime.json` to a private backup location.
The cache can be rebuilt, but its pinned commit must remain available in Git
history. Use the ignored `backups/` directory for any backups kept here. Removing
a file from tracking does not erase earlier committed copies from Git history.

To change coaching rules or software, open a separate session in
[`../workflow`](../workflow/). Practice records remain here in one place.
