# Workflow development

[English](README.md) · [한국어](README.ko.md)

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
against their original conditions. Generated exercises have immutable self-contained
contracts; legacy self-reports keep their original scoring semantics.

Commit validated source and create a version tag before publishing. This example
selects `v0.6.1`; create a new tag for later releases instead of moving an old tag:

```sh
uv run python publish.py --ref v0.6.1
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

Version 0.3.0 connects **New practice** to local Codex analysis and generation. The
Python standard-library server defaults to loopback; playback and MIDI capture use
Web Audio/Web MIDI. Generation needs the installed Codex CLI, an existing login,
network access and available usage allowance. No separate API key is required.
It does not fall back to rule-selected exercises when Codex fails.
The interface defaults to English. **Settings → Display language** switches between
English and Korean and remembers the choice in this browser at the same address
and port. Switching preserves active capture and unfinished report inputs. Agents
follow the user's conversation language independently. Original notes and historical
evidence retain their original wording.

The first screen is your **Practice list**, grouped by date. Each item shows its
exercise, key and target tempo, ready/in-progress/completed/skipped status, feedback,
memo and optional skip reason. The navigation contains Practice and Settings.
The former history tab is part of this list; the progress dashboard is removed.

**New practice** analyzes the explicit profile, recent records, feedback, notes and
skip reasons, shows generation status, then adds a validated item without opening
the room or starting playback. Click the new item to enter. Only one unfinished assignment is
allowed; return to that item to continue or skip it before adding another.
The optional focus field sits immediately above **New practice**. It hides while
the request is being submitted or generated, and the progress message acknowledges
an included focus. Successful generation clears the submitted text; a failure keeps
it available for editing or retry. Practice filters follow these creation controls.
**Complete practice** saves input, closes the task, and returns to the list. Add
feedback in the completed item: 😈 Impossible, 💪 Challenging, 🙂 Good practice,
or 🙄 Too easy to be useful. A tap saves it; a memo is optional. Completion does not
wait for feedback, and adding or editing feedback never counts the practice twice.

Completed items open their saved details. **Practice again** prepares a separate
new assignment, which is added to the list before you enter it. Returning to the
list during practice saves the current recording while leaving the task unfinished.
No page load, item creation or recording recovery automatically enters the room.

Once a web-capable version is active, run this from the repository root. `uv`
prepares the environment; `jazz` with no arguments runs `serve --open`:

```sh
uv run --project practice jazz
```

The server defaults to `http://127.0.0.1:8765`. Use `--port 8768` if needed,
and Ctrl+C to stop. After publishing a new version, restart the server.
Unfinished tasks do not block activation. Return with
the same browser, address, and port to recover pending MIDI uploads; recovery also
preserves input attached to retired tasks without creating a performance report.

For access from other devices on a trusted LAN, explicitly choose a listen address:

```sh
uv run --project practice jazz serve --host 0.0.0.0 --port 8768 --open
```

Open `http://<server-LAN-IP>:8768` on the other device. `0.0.0.0` listens on all
IPv4 interfaces; use a specific local IPv4 address to bind only that interface.
`localhost` is also accepted; other hostnames and IPv6 are not supported.
`--open` opens a browser on the server computer. No firewall rules are changed.
There is no login: reachable devices can read and change practice records and
request recommendations using the server's Codex account. Host, same-origin and
CSRF checks remain enabled; they do not authenticate LAN users.
Practice generation, metronome playback and saving work over plain HTTP. Web MIDI
requires HTTPS or localhost in a supporting browser; this server does not provide
TLS. To use MIDI remotely without HTTPS, forward the port through SSH and visit
localhost on the client. Changing the address creates a separate browser storage
origin, so recover any unsent input at its original address first.

- **Practice room:** the purpose, conditions, characteristics and saved personal
  prediction appear before the score. Expand **Practice plan** for the rhythm and
  ordered steps, or **Notes and chord progression** for the written parts (opened
  automatically when no score is available). These choices stay open when the
  language changes. **Go to score** moves keyboard focus to the player, clear of
  the mobile MIDI header. Start, complete and tempo controls sit above the score;
  narrow screens stack them without squeezing the buttons. Target BPM and current
  metronome BPM are separate. Choose tempo before starting: the input, slider and
  buttons stay locked until the recording ends, including pauses. Expand **Sound
  settings** for volume and chord pad. MIDI connection, status and input selection
  stay in the sidebar, or the sticky top area on mobile. Click and pad share the same
  beat clock. Resuming starts from the first bar; switching away from the tab
  pauses playback.
- **Score and live input:** a grand staff shows the assigned parts, chord symbols,
  key signature, and rhythm. Blue MIDI marks keep fractional timing against the
  playback clock; their tails show physical key holds, excluding pedal sustain.
  Scores wrap every four bars at every screen size and fit
  the available width. The cursor moves continuously within each line and then
  moves to the next line. **Follow playback** brings that line into view when
  needed; turn it off to scroll manually. MIDI holds crossing a line continue
  on the following staff without an extra attack mark. Resizing preserves the
  current beat and MIDI buffer; layout never changes the saved music. Whole-note
  centers are transparent, and the score omits bar numbers and hand labels.
  Improvisation has allowed pitches and rest bars, with no invented melody; bass
  diamonds mean a beat-1 attack whose
  hold length is unspecified. Input placement follows the assigned staff or pitch
  range, not detected hands. This view does not assess correctness or fill reports.
  Charleston eighth notes illustrate short attacks on 1 and 2&; the illustration
  does not add an exact hold-duration requirement to the assignment.
- **Complete practice:** save recording and measured time, close the task, and return
  to the list. Feedback is editable there. A completed task without a label has
  unknown musical correctness; it is not an unfinished assignment.
- **Discard task:** close an unfinished item with an optional reason. The room saves
  any active recording first. A failed save leaves the task open for retry. Existing
  input is preserved. The optional reason is context for future coaching, not a
  performance report or mastery credit. An empty reason stays unknown.
- **Saved details:** inspect the original conditions, notes, edits and raw MIDI.
  Corrections preserve earlier reports. Feedback is also visible directly in the list.

Each generated exercise includes its purpose, selection reason, section, key, target
BPM, hand roles, specific notes/rhythm, steps and proposed practice time. **Why this
practice?** separates the coach's interpretations and source IDs from unknowns;
the original context is available locally. The existing curriculum is optional
reference material, not a candidate list, required sequence, or set of unlocked keys.
New tasks can use any key and 20–240 BPM. New schema-3 scores store canonical ABC
(`jazz-abc-1`): 1–16 full bars of fixed 3/4 or 4/4, two staves with up to two voices
each, chords/rests, sixteenth through whole notes, dots, ties, ordinary triplets,
dynamics and accents. The goal determines form length, including 8-bar phrases and
12-bar blues. Unsupported notation is rejected, never silently simplified. Legacy
schema-1/2 JSON scores remain unchanged. Open improvisation can use
specific written instructions with an explicit reason for omitting fixed notation.

MIDI is optional. In a browser supporting Web MIDI on HTTPS or localhost, choose
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
Add `--host 0.0.0.0` to the preview command to access it over LAN. The same HTTP
and MIDI limitations apply; use this preview directory for development records.

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
completion events and self-reports, linked to sessions by `task_id`. Ending an
individual recording does not complete the task. The explicit Complete practice
operation appends completion; feedback can be added separately afterward.

Git does not preserve personal records. Stop the server before backing up the CSV,
SQLite database, profile, feedback notes, `.recommendations/`, `.translations/`, and `runtime.json` together to a private
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
Checks also cover translated descriptions during capture, fixed BPM while playing
and paused, and the MIDI connection control remaining visible on mobile. Layout
checks cover 320–1440 px, aligned journal content, expandable plans, keyboard
navigation to the player and consistent notation size under the server's CSP.

The optional LAN browser check requires this computer's actual non-loopback IPv4
address. It uses temporary synthetic records and verifies an ordinary HTTP origin,
including generation, recording completion, feedback, repeat and MIDI messaging:

```sh
JAZZ_TEST_LAN_HOST='<server-LAN-IP>' \
PLAYWRIGHT_MODULE="$PWD/build/browser-tools/node_modules/playwright/index.mjs" \
CHROME_EXECUTABLE=/usr/bin/google-chrome node tests/browser-lan.mjs
```

## ABC runtime and teaching materials

Install Node.js 20 or later alongside Python/uv. Python invokes the bundled parser
in a short Node subprocess; the browser uses the matching bundled abcjs renderer.
The launcher and publisher check Node before running/activating an ABC release.
`JAZZ_NODE_BIN` can name its executable. Normal use needs no npm install or browser
process on the server. Development bundle changes use `npm ci` and
`npm run build:notation` followed by the music interoperability checks.

Generation pins `gpt-6.1-sol` with `model_reasoning_effort="high"`. It first asks for
an evidence-based learning goal and material requests, then the app retrieves
sources, and a fresh explicit call writes the exercise. One music-only validation
repair is allowed; it cannot change evidence, goal, prose, difficulty or citations.
Calls have a four-minute limit within a ten-minute request deadline. Auth/quota/
connection failures do not trigger a fallback or a weaker model. Requested settings,
CLI version, usage and elapsed time are recorded; unobserved effective model
configuration is left unknown. Translation keeps its separate prose-only protocol.

`materials-catalog.json` contains public source metadata and links, including Open
Studio, Open Music Theory and other teaching sites. It is not a fixed exercise list.
Sources are fetched only on request into
`${XDG_CACHE_HOME:-~/.cache}/my-jazz-tutor/materials/`; `JAZZ_MATERIALS_CACHE` selects
another local cache (tests use temporary directories). Original bytes are addressed
by SHA-256, with URL, retrieval time, ETag and Last-Modified metadata. Refresh uses
conditional requests; old snapshots never follow a changed source. SQLite FTS5
searches section/page text and reviewed units (objectives, tags and reviewed scope).
Example queries use AND then at most one OR relaxation; no hit is explicit, without
an unrelated first-page substitute. Only the current source hash is searched.
At most two sources and three excerpts/page images are supplied per generation.
The best match from each requested source gets a slot before either source gets
another. Unavailable sources/pages do not consume a slot. `material_omissions`
lists matched sections excluded by the shared budget; they are not unreadable or
evidence of a failed search. Only supplied excerpts may be cited. PDF image numbers
follow the final excerpt order, and omitted pages are not rendered for the request.
Downloads are capped at 40 MB and PDFs at 300 pages;
images are capped at three MB each. Text still fits the 64,000-byte prompt/schema
budget; images are separately bounded and are not counted as text tokens.

The model receives the retrieved content explicitly. A cached path or PDF text is
not proof that an image score was inspected. Source failures remain in the request
artifact/context. The model may create an original exercise when no source fits,
with honest attribution; no fixed-curriculum fallback is used.

References appear in the room and completed details with author, title, URL and
page/section. Unchanged examples, adapted examples (including changes), and teaching
concept references are distinct. Exact reuse requires a reviewed ABC cache asset;
the model selects its ID and the app inserts its notation. Review compares source
bytes and the exact excerpt with pitch, duration, spelling, voice and expression.
The review record identifies its author and method; it is not automatic proof of
musical/source correctness. Goal plans include `example_requirements`: required
key/bar count (null when flexible) and focus terms. The app blocks unchanged reuse
when these conditions differ; educational suitability still requires the teacher's
explanation. A lexical match is not a guarantee of learning-goal fit.

For local material inspection and explicit reviewed imports:

```sh
uv run --project practice jazz material-catalog
uv run --project practice jazz material-source openstudio-beginners --pages 44
uv run --project practice jazz material-import --input /tmp/reviewed-example.json
```

The import JSON contains `source_id`, an exact returned `locator`, `notation`
(the ABC envelope), and `review` with `source_sha256`, `reviewer`, `scope`, `notes`,
`method` (`visual_source_comparison` or `symbolic_source_comparison`), and `checked`
containing `pitches`, `durations`, `spelling`, `voices`, `expression`. This explicit
review path is not available to the tool-free generation model. Downloaded content,
transcriptions and personal contexts must never be committed.

### Extraction workbench (0.6.0)

`score_extract.py` creates **unreviewed** candidates in an explicit local cache.
It never reads/writes practice records and is not a recommendation-model tool.
Sources, crops/frames, raw MusicXML/MXL, logs, corrections and ABC remain outside
Git. Extraction and registration are explicit operations, separate from generation.

```sh
uv run python score_extract.py --cache build/materials extract --input /tmp/extract.json
uv run python score_extract.py --cache build/materials compare CAND-… --output build/source-review
uv run python score_extract.py --cache build/materials compare CAND-… --notation /tmp/corrected-abc.json --output build/source-review
uv run python score_extract.py --cache build/materials register CAND-… --input /tmp/source-review.json
```

Requests supply `source_id`, an exact returned `locator`, and `selection`. Example:
`{"kind":"pdf","page":44,"crop":[0.06,0.25,0.53,0.15],"first":1,"last":4,
"missing_key":"C","missing_meter":"4/4"}`. Crop is normalized x/y/width/height;
inspect it before review. Missing headers require explicit source inspection and
never override existing headers. `first`/`last` are measure positions within the
extracted score, not printed numbers. `kind:"musicxml"` imports a cached XML/MXL
source. `kind:"video"` uses `seconds` and `crop` to select one frame of a directly
downloadable file within the 40 MB limit. `--catalog` can name a local pilot catalog.

PDF/image OMR needs external [Audiveris](https://github.com/Audiveris/audiveris)
(`JAZZ_AUDIVERIS_BIN`); video frames also need ffmpeg (`JAZZ_FFMPEG_BIN`). Tools are
never installed automatically. Pin the tool version and bound Java's heap in a
wrapper. The Linux 5.11.0 pilot used its embedded JRE with `-Xms128m -Xmx1500m`.
The app runs `-batch -export` with a 120-second timeout and kills the process group
on timeout. Missing tools/invalid output leave an issue and an unreviewed candidate.
The pilot lacked English OCR data, so chord symbols required manual restoration.
Tool installation/licensing stays separate from the small runtime dependencies.

The conservative importer supports a single piano part, two fixed treble/bass
staves, 3/4 or 4/4, 1–16 complete measures, up to two voices per staff, spelled
chords, dots, ordinary triplets, ties, basic dynamics/articulations. It compares the
MusicXML timeline with parsed ABC. Unsupported slurs, ornaments, repeats/endings,
changing keys/clefs and incomplete bars stop conversion; no rests or notes are
invented. Printed accidentals (including plain cautionary signs) are retained;
other signs appear only when required by the key, current bar, octave and voice.
Parenthesized/custom signs require review instead of silently losing their display.
Layout/beaming normalization is disclosed. This
is not a general MusicXML converter and does not certify image fidelity.

Registration JSON contains `review` (the fields above plus `candidate_id` and
`corrections`), optional corrected `notation`, and optional `learning` with
`objectives` and `tags` arrays. Failed/changed extraction requires explicit
corrections. Candidate/source hashes bind the receipt to the inspected bytes.
Only registered examples enter retrieval. Transposition/rearrangement relative to
the actual source is an adaptation, not an extraction correction.

The OMR pilot covers one clean public PDF excerpt and synthetic XML/video transport.
It does not establish real-video accuracy, broad library coverage, frame selection/
deduplication, audio transcription or semantic search quality. Embeddings await a
measured lexical-search limitation. `tests/materials_compare_smoke.py --run` compares
complete recommendation paths with copied public caches and identical synthetic
history in temporary directories. A single pair is a functional check, not a quality
trend or proof of suitability for a real learner.

`tests/coaching_consistency.py` adds three synthetic feedback cases: too easy,
challenging but useful, and an unattempted task skipped because of repetition.
It leaves musical choices to the coach rather than prescribing pitches, a source
page or form length. Each run creates temporary records, copies the supplied public
cache and preserves both successful and failed outputs. Use frozen source snapshots
and the same cache for both versions; do not edit those snapshots during a batch.

```sh
# Setup check only; remove --prepare-only for an explicit real Codex call.
uv run python tests/coaching_consistency.py --run --prepare-only \
  --workflow build/coaching-consistency/candidate-source \
  --cache-seed build/coaching-consistency/materials \
  --output build/coaching-consistency/setup-example --scenario bored_skip --replicate 1
# Render every paired run, its score/audio preview, source crops and review notes:
uv run python tests/coaching_comparison_report.py --experiment build/coaching-consistency
```

The report reads local `protocol.json`, `runs/<scenario>-<replicate>-<version>/`,
optional `review.json`, and optional `library-new.json` source-review artifacts.
It does not invoke Codex or publish a release. Repeated fixed-history trials probe
consistency and variety, not longitudinal learning or calibrated human difficulty.
Keep public scores, downloaded PDFs, test outputs and source-review receipts local;
the repository contains the harness, catalog links and schemas only.

## Codex recommendations and conversational coaching

Verify the local CLI with `codex --version` and `codex login status`. If necessary,
run `codex login` in a terminal. The app locates `codex` on PATH, then
`~/.local/bin/codex`; `JAZZ_CODEX_BIN` can select another executable. It runs
`codex exec --sandbox read-only --ephemeral --json --output-schema ...` from an empty
temporary directory, ignores user configuration/rules, and disables shell, plugins,
hooks, browser and delegation tools. Existing CLI authentication is reused. It does
not resume a chat or assume any shared conversation memory.

Each explicit request supplies the shared `coaching-policy.txt` and
`notation-policy.txt` contracts, profile provenance, optional request text,
the difficulty rubric, up to eight recent tasks and four related/corrected older tasks.
Conditions are compact descriptions and score features; full scores stay in original
snapshots. Latest feedback, exact note/skip excerpts and up to three recent session
summaries per task retain source IDs. An all-history factual rollup counts current
states and latest labels, preserves dated example excerpts, and joins original
burden predictions with later feedback. It rebuilds from the ledger after corrections,
without promoting earlier interpretations to performance facts or summarizing old summaries. Related history selection
uses request text, key and focus axes; it does not restrict generated exercises.
The app-supplied prompt plus output schema is limited to 64,000 UTF-8 bytes (a
conservative text-token upper bound, not a tokenizer count or total CLI input usage).
Descriptions are shortened with explicit omission metadata and fewer cases are
included when necessary. A profile/request/rules bundle that alone exceeds the
budget fails explicitly. Original records are never shortened. Coverage and omitted
detail counts are supplied; omitted history does not mean unpracticed. Raw MIDI is
not sent. The private request artifact preserves the exact assembled context. Context
sent to Codex uses the account's remote model service; local files are not model
write targets. Login expiry, quota, connection, timeout and invalid
output are visible failures, with no substitute fixed recommendation.

The app checks the JSON schema, evidence references, piano pitches, bar counts,
ordered note/rest coverage and matching accompaniment. This verifies representation,
not the musical quality or complete semantic agreement of prose and score. Model
interpretations remain labeled. A G- ID identifies generated conditions and a T- ID
identifies an attempt. Immutable conditions are stored in `practice.csv`; the exact
input/result/provenance are private `.recommendations/R-….json` artifacts. Requests
are idempotent and single-flight across servers. A changed profile, record, session
or runtime invalidates an in-flight result. Restarted jobs recover saved items or
show an interrupted error. Restart the server after activating a release.

Schema-2 and schema-3 tasks include seven separate demand axes: melody, rhythm, meter,
tonality, harmony/voicing, expression and hand coordination. `difficulty-rubric.json`
uses an extensible ordinal scale with registered comparison anchors. Its initial
anchors 1–3 are not low/moderate/high bands or a maximum musical difficulty.
New anchors require a new rubric version; an unregistered level is rejected.
They are provisional, unvalidated ordinal references, never a required curriculum,
equal-interval scale or overall ability score. Unsupported meters in reference
examples do not extend the notation renderer. Unknown, inapplicable and out-of-range
demands have no numerical level. The app validates axis/anchor/level consistency and
source IDs, and independently derives facts from assigned notation. It does not
certify the musical judgment or infer a fingering from pitch distance.

The list, room and past records put concrete task characteristics and the personal
burden prediction first. Characteristics come from the saved conditions and notation,
such as offbeat entries, rests and differing hand entries. Internal stages, demand
bands and anchor comparisons are hidden. Expand the conditions and prediction
evidence for the written hand/rhythm instructions, reasoning and uncertainty.
Prediction is the forecast saved when assigned, not a current ability score or probability.
The next request compares it with latest feedback under comparable conditions;
there is no label-to-BPM rule or automatic ability update. `good` means useful, not
medium difficulty; `challenging` is not failure. Repeated copies retain the original
prediction and are excluded from aggregate new-forecast counts. Translation changes
only explanatory prose, preserving levels, anchor IDs, music and computed facts.
The same presentation applies to historical tasks without rewriting their snapshots,
reports or MIDI. Tasks without a saved forecast say so; no earlier prediction is
invented from later feedback. Schema-version-1 snapshots and the archived
`difficulty-rubric.v1.json` remain supported. Assessment snapshots and rubric versions
never change when feedback is corrected. Near the context budget, recent tasks and
related/corrected older tasks are interleaved so recency cannot exhaust all space first.

Calibration checks cover anchor validation, score facts under wording/tempo changes,
translation invariance, prospective-feedback joins, corrections and long histories.
These checks establish software consistency, not empirically validated musical
difficulty or reliable performance prediction. Local history processing still scans
the ledger; the model input remains bounded as that ledger grows.

New recommendations always have an English original, regardless of the display
language or profile language. `context.language` is `en`; `display_language` records
the UI preference. This also applies to conversationally accepted recommendations.
The `--language` option selects that preference, not the canonical prose language.

When a Korean screen needs a generated practice, the browser requests its translation
through `POST /api/translate`. The same Codex login and read-only structured-output
runner translate the title, instructions, hand roles, notes/rhythm prose, steps,
rationale, interpretations and unknowns. It receives those strings, not a new profile
or history analysis. The app accepts only the expected prose fields, protects written
numbers/pitches/chord names with placeholders, and copies structured music, source
IDs and confidence unchanged. These checks do not prove complete semantic equivalence.
Korean musical terms may contain a numeral only when the same English concept occurs
in that field (for example, quarter note → 4분음표, eighth-note rest → 8분쉼표, or
seventh chord → 7화음). Standard spacing such as 4분 음표 is accepted. Written counts
and positions with explicit units (four bars, third beat, seventy-two BPM) are
normalized only in the translation input and protected by the same placeholders.
The model receives their values for context but must return the placeholders.
New tempo, count or pitch values still fail validation.

Translations are cached locally in `practice/.translations/` by original snapshot,
language and format. One worker translates items sequentially; repeats of the same
snapshot reuse the cache. Reads never start model requests. While translating or
after failure, the original stays available with status and an explicit retry button.
Successful translations survive reloads and version updates with a compatible format.
Earlier caches retain their original placeholder protocol, without a new model call.
Within an explicit translation request, a rejected field gets at most one targeted
repair attempt; validated fields are kept. A failed repair leaves the original
available and requires an explicit retry. Login, quota, connection and timeout errors
do not automatically retry. Each Codex call has the four-minute timeout.
Returned attempts and field-level validation diagnostics remain in the private
translation artifact for offline debugging; they are not sent in the web state or
committed to Git. Rejections from before this release did not retain the model output.
Historical snapshots and user notes are never rewritten. For older generated tasks,
the source language comes from their original generation artifact if available; an
unknown language is not inferred from the current profile. Built-in legacy tasks
continue to use their existing presentation catalog.

From the repository root, when the user requests a new practice:

```sh
uv run --project practice jazz recommend --language en
# suggest is an alias: it also generates AND stores a new item.
```

A conversational coach can perform the analysis itself using the same protocol:

```sh
uv run --project practice jazz recommend-context --output /tmp/jazz-context.json
uv run --project practice jazz recommendation-plan-schema
# Write the goal/material plan first, then let the app fetch the requested sources:
uv run --project practice jazz recommend-materials --context /tmp/jazz-context.json --plan /tmp/jazz-plan.json --output /tmp/jazz-prepared.json
# Read the supplied excerpts and inspect any listed images before composing:
uv run --project practice jazz recommendation-schema
# Write one matching recommendation JSON to a temporary file, then validate/save:
uv run --project practice jazz accept-recommendation --context /tmp/jazz-prepared.json --input /tmp/jazz-recommendation.json
```

These commands use the same records, guidelines, schema, validator and storage as
the web app. Acceptance verifies that the context has not been edited or become
stale. Do not edit the CSV or installed sources directly. Generated criteria describe
the practice goal and do not manufacture success checks. Labels and notes are user
feedback, and metronome settings are never analyzed playing tempo.

`status` only reads navigation and records; it does not call Codex. `report` exports
local records without creating a recommendation. The explicit legacy `assign E01`,
`record`, `correct`, and `cancel` commands remain for historical compatibility;
they do not define the new recommendation route. `discard TASK --reason ...` accepts
an optional reason and preserves recordings. `reflection TASK --input /tmp/feedback.json`
uses the same four labels and optional note as the web: `{"rating":"good","note":""}`.
When editing, include the current `expected_event_id`. Actual observations and old
notes are preserved. Never fill unknown checks from a difficulty label.

Manual real-connection test (synthetic context and temporary records only; verifies
English generation from a Korean request and a subsequent Korean translation):

```sh
uv run python tests/codex_smoke.py --run
uv run python tests/calibration_smoke.py --run
uv run python tests/translation_smoke.py --run
```

This consumes the logged-in account's Codex allowance. Normal unit and browser tests
use an explicitly injected synthetic provider and never require an account or network.
The provider is not available as a production fallback.
The calibration smoke test independently assesses fixed synthetic music, checks
invariance to wording/language and compares an unseen offbeat variation with a
regular pulse. Its private `build/` report records results and usage. Passing this
small regression suite is not evidence of empirically calibrated human difficulty.
The translation smoke test uses synthetic musical text and deliberately removes a
placeholder from a real model response to check the bounded repair path, Korean rest
terminology, counts, and preservation of the original conditions and MIDI.

CLI reference: [noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[authentication](https://learn.chatgpt.com/docs/auth). A persistent
[app-server integration](https://learn.chatgpt.com/docs/app-server) is not needed for
these single requests.

## CSV structure

Append events only to `practice/practice.csv`. `task_id` links assignments and
results; `event_id` identifies each event. Writes use a file lock.

| Main column | Meaning |
| --- | --- |
| event_type | assigned / completed / reported / corrected / discarded / cancelled / retired |
| target_json | Assigned key, BPM, hands, rhythm, bass, voicing, melody, material, and criteria |
| actual_json | Conditions the user reports actually practicing |
| checks_json | Notes, pulse, and uninterrupted playing: true / false / null |
| clean_runs | Consecutive successful runs under the conditions; empty when unknown |
| raw_note | Original user text, including commas and newlines; optional with a web label |
| difficulty | Web labels: impossible / challenging / good / too_easy; legacy CLI values retained |
| reason | Assignment/legacy closure text; completed/reflection events store a session-reflection-v1 timing snapshot; discarded events store choice + exact note JSON |
| hypothesis | Coach interpretation, separate from the original note |
| supersedes | ID of the previous result replaced by a correction |

Scripts calculate metrics. The LLM must not store invented overall ability scores.
Reports do not alter evidence and can be deleted and regenerated.
