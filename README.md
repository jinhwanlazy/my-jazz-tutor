# My Jazz Tutor

Your private AI jazz piano tutor, powered by Codex.

[English](README.md) · [한국어](README.ko.md)

This is a local piano tutor using your Codex login. Both conversational coaching
and **New practice** in the browser analyze an explicit profile and actual records,
feedback, notes and skip reasons to compose the next exercise. The curriculum is
optional reference material, not a fixed sequence. The local practice room provides
a metronome, optional accompaniment, notation and MIDI capture. The app validates
Codex's structured result before creating an immutable task.

The `my-jazz-tutor/` Git monorepo contains two work areas. Open the directory for
your intended role and follow its `AGENTS.md`. Paths and commands below are relative
to the repository root.

| Work area | Directory | Example opening message |
| --- | --- | --- |
| Daily practice | [`practice/`](practice/) | `Let's practice. Read my records and suggest one task.` |
| Workflow development | [`workflow/`](workflow/) | `Read my practice records and review the recommendation rules.` |

You can start a separate Codex session in either directory:

```sh
codex -C practice
codex -C workflow
```

Run these in separate sessions. Changing directories alone does not reset a
session's role. Agents respond in the language you use, unless you request another
language. Documentation uses English. The web interface starts in English and
offers English/Korean switching under **Settings → Display language**.

Git manages both areas from the repository root; there are no nested repositories
or submodules. It tracks source, tests, documentation, an example profile, and the
initial runtime ref. Runtime history lives in Git commits and tags. **Personal
practice data stays local.** The root `.gitignore` excludes the original CSV,
personal profile, MIDI database, feedback notes, generated reports, backups,
virtual environments, caches, and development previews.

After cloning, follow [practice setup](practice/README.md) to copy the example
profile and enter your preferences. CSV and MIDI storage are created when needed.
Checking out Git history or cloning again does not restore personal records;
back them up separately.

The single practice log is `practice/practice.csv`. Development sessions may read
it to improve the design, but must never write test results into it. Practice runs
the Git commit pinned in local `practice/runtime.json`. Execution files are
materialized as needed in the ignored `practice/.runtime/<commit>/` cache. Deleting
the cache restores the same commit; working source changes are not activated
automatically. A new workspace pins the tag in `practice/runtime-ref` on first run.

```sh
uv run --project practice jazz status
uv run --project practice jazz report
uv run --project practice jazz runtime
```

Open the generated `practice/reports/index.html` in your browser. No external
server, additional LLM API key, or Streamlit server is needed. Each project's
Python environment is managed with `uv`.

The local practice room is available in runtime 0.2.0 and later. Once a web-capable
version is active, start the server and open your browser with:

```sh
uv run --project practice jazz
```

The landing screen is a dated practice list. New practice shows generation progress
and adds an item; open it explicitly to enter the room. Complete practice saves
recording and measurements and returns to the list. Leave one of four difficulty
labels and an optional memo there. Feedback is editable independently of completion.
Skipped items retain optional reasons. Practice again creates a separate attempt.
A continuous grand staff shows assigned notes and live input. Musical MIDI scoring
is not implemented; recorded BPM values are metronome settings.
MIDI connection stays visible in the sidebar (at the top on mobile). Choose BPM
before recording; it stays fixed while playing and paused until that recording ends.
New exercises are saved in English and translated by Codex for Korean display.
Translations are cached separately; original conditions and user notes stay intact.

Generation requires an installed Codex CLI, a working login (`codex login status`),
network access and available usage allowance. No separate API key is required.
Only the explicit coaching context is sent; there is no shared chat memory. Errors
are shown instead of replacing a failed request with fixed-curriculum recommendations.
Personal recommendation artifacts and translation caches remain local and excluded from Git.

Raw MIDI is stored in `practice/sessions.sqlite3`. See the
[workflow README](workflow/README.md#web-practice-room) for startup, activation,
development previews, and recovery.

With no arguments, `jazz` runs `serve --open`; no separate environment activation
or installation command is required. To use another port, run
`uv run --project practice jazz serve --open --port 8768`. The launcher follows the
local pinned commit. Publishing from `workflow/` activates the selected release by
default, carries compatible unfinished tasks, and retires incompatible tasks while
preserving their history and MIDI. Use `--cache-only` to defer activation; restart
the practice server after publishing.

For trusted LAN access, add `--host 0.0.0.0` and open the server's LAN IP and port
from another device. The server has no login; Web MIDI requires HTTPS or localhost.
See [LAN setup](workflow/README.md#web-practice-room) for details and development previews.

Role boundaries are enforced by directory instructions and runtime publication.
They are operating conventions, not an OS sandbox blocking access to other files.
