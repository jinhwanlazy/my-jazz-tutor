# Daily practice

[English](README.md) · [한국어](README.ko.md)

This is the daily practice area of the `my-jazz-tutor/` monorepo. Workflow
development belongs in `../workflow`; both areas share the root Git repository.
The commands below run from the repository root.

Install Python 3.11+, uv and Node.js 20+ before launching. New ABC scores use the
bundled abcjs parser/renderer; npm is not required for normal practice.

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

`recommend` (also `suggest`) asks the local Codex CLI to analyze explicit context
and add one validated practice. It requires Codex installation, login, network and
available allowance; no separate API key is needed. `status` is read-only. `report`
exports local records and never generates assignments. See the shared
[recommendation protocol](../workflow/README.md#codex-recommendations-and-conversational-coaching)
for direct conversational coaching and error handling.

Start the local server and open the browser:

```sh
uv run --project practice jazz
```

The first screen is your dated **Practice list**, including content, status, result,
memo and optional skip reason. **New practice** reviews your profile and recent
practice feedback, shows progress and adds a validated item without opening it.
Click the item to enter. **Complete practice** saves recordings and measured time,
then returns to the list. Tap 😈 Impossible, 💪 Challenging, 🙂 Good practice, or
🙄 Too easy to be useful; a memo is optional. You can leave or edit feedback later.
A completed item opens its details; **Practice again** explicitly creates another
attempt. Skip unfinished tasks with an optional reason. No separate progress or
history tab is required.

The score and playback controls share one area below the task description. A
continuous cursor and horizontal scrolling follow the entire score. Transparent
whole/half notes preserve staff lines. MIDI traces show physical key holds, not
pedal sustain or timing scores. Recording continues during pauses. Generated scores
support fixed 3/4 or 4/4, 1–16 bars, independent voices, chords/rests, sixteenth
through whole notes, dots, ties, triplets and written expression; other
exercises may have specific written instructions instead. Notes are not restricted
to the example curriculum's keys or fixed exercises.

Generation uses Sol/high to choose a learning goal before retrieving any teaching
materials. Relevant pages are downloaded on request into the local material cache,
then explicitly supplied to the model. References show the author, link and excerpt,
and distinguish original source examples, adaptations and conceptual references.
Verified examples can be reused exactly; automatic PDF/video transcription is not
included. See the [source cache and ABC protocol](../workflow/README.md#abc-runtime-and-teaching-materials).

Recorded BPM is the metronome setting, not an analysis of your actual playing tempo.
Labels are subjective feedback, not accuracy or mastery. The app does not ask you
to enter measured BPM, time, date, or correctness checks again. **Why this practice?**
shows the coach's interpretations, source IDs and unknowns separately.

Settings switches English/Korean while preserving active input and unsaved memos.
New exercises are saved in English first. Korean screens request a Codex translation
and reuse the cached copy afterward. Titles, descriptions, steps and coaching
explanations switch languages; your notes and original conditions stay intact.
Translation status and retry controls appear alongside the original when needed.
The **Practice** sidebar also keeps MIDI connection and input selection visible.
Choose BPM before starting; it remains locked through pauses until recording ends.
Recommendations
send explicit context through your Codex login; they never assume access to the
current chat. Failures show retry instructions and do not create a fallback exercise.

The address is `http://127.0.0.1:8765`; stop the server with Ctrl+C. If the port is
busy, use `uv run --project practice jazz serve --open --port 8768`. To start without
opening a browser, use `uv run --project practice jazz serve`. Running `./jazz`
inside this directory also remains supported. Records stay in the existing CSV
and `sessions.sqlite3`. To recover unsent input, return with the same browser,
address, and port, then choose **Recover practice**.

For a trusted LAN, run `uv run --project practice jazz serve --host 0.0.0.0 --port 8768`
and open `http://<server-LAN-IP>:8768` on another device. You may bind a specific
local IPv4 address instead. There is no login: reachable devices can access your
records and request recommendations. Generation, metronome and saving work over
HTTP; MIDI requires HTTPS or localhost. See the
[LAN setup and limitations](../workflow/README.md#web-practice-room).

`uv run --project practice jazz runtime` shows the active version, Git commit, and
cache location. First launch resolves `runtime-ref` to a commit in local
`runtime.json`. Later source or tag changes do not change that pin. Deleting the
`.runtime/` cache reconstructs the same commit from local Git history.

Publishing activates the selected release even with unfinished tasks. From the
repository root, run `uv run --project workflow python workflow/publish.py --ref v0.5.0`.
Compatible tasks keep their original conditions; incompatible tasks are retired
with a reason while preserving history and MIDI. Retirement is not a performance
result or a skip. Use `--cache-only` to prepare without activating, and restart the
practice server after activation. Launching alone follows the existing pin.

`practice.csv`, `profile.json`, `workflow-feedback.md`, `sessions.sqlite3`,
`runtime.json`, `active-version`, `.runtime/`, `.recommendations/`, `.translations/`, `reports/`, and `backups/` are ignored
by Git. `active-version` is for legacy compatibility; `runtime.json` selects the
active code. The CSV is created when the first task is assigned, and MIDI storage
when the first recording starts. Add local workflow feedback notes as needed.
Missing files mean no data has been recorded; do not fill them with sample results.

Git does not back up personal records. Stop the server, then copy the CSV, SQLite
database, profile, feedback notes, `.recommendations/`, `.translations/`, and `runtime.json` to a private backup location.
The cache can be rebuilt, but its pinned commit must remain available in Git
history. Use the ignored `backups/` directory for any backups kept here. Removing
a file from tracking does not erase earlier committed copies from Git history.

To change coaching rules or software, open a separate session in
[`../workflow`](../workflow/). Practice records remain here in one place.
