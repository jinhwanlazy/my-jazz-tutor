# My Jazz Tutor

Your private AI jazz piano tutor, powered by Codex.

[English](README.md) · [Korean original](README.ko.md)

This is **a local experiment in building a private piano tutor around a Codex
subscription**, rather than a deployed service. Codex conversations handle
assignments and practice context, while a local practice room provides a metronome,
optional accompaniment, and recording. Web feedback currently compares your reports
with fixed criteria using rules.

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

The interface covers assignments, practice reports, rule-based feedback, history,
and corrections. It includes a metronome, optional chord pad, raw Web MIDI capture,
and suggested BPM and duration values. A grand staff shows the assigned notes and
rhythm, with a moving beat cursor and live MIDI marks. Musical MIDI scoring is not
implemented.
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

Role boundaries are enforced by directory instructions and runtime publication.
They are operating conventions, not an OS sandbox blocking access to other files.
