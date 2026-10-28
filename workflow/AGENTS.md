# Role: workflow designer and maintainer

This project develops the jazz practice system. Respond in the user's language and
critically review proposals. Do not turn a design discussion into implementation unless the
user requests implementation. Read `DESIGN.md`, `README.md`, `curriculum.yaml`, and
`COACH.md` before changing behavior.

## Separation from practice

- Production data lives in `../practice/`. Read it when relevant, never fabricate
  reports or run test assignments against it.
- Personal records, profiles, MIDI sessions, and feedback notes are local-only and
  ignored by Git. Never force-add them or copy them into tracked docs or fixtures.
- Tests use temporary directories. Development previews use `build/` or a temporary
  directory, not the production reports directory.
- Edit source files here. Do not edit an installed release in place.
- A change to source does not activate it. Commit runtime changes, then use
  `publish.py --ref <commit-or-tag>` to validate and cache that Git snapshot.
  Publication activates the selected version by default; `--cache-only` explicitly
  prepares a cache without activation. Carry compatible unfinished tasks with their
  original snapshots; retire incompatible ones with a reason, preserving history
  and MIDI. Unfinished tasks do not block upgrades or imply failure/unpracticed status.
  Never commit runtime copies or the local active pin; Git commits/tags retain version history.
- Publish when the user's task includes applying/releasing the change. Do not add
  a permission round trip if that action is already authorized.
- Initial workspace setup and initial release are authorized by the setup request.

## Invariants

- Preserve original notes and separate assigned conditions from actual conditions.
- Missing observations are unknown. Self-reports are not audio verification.
- Keep legacy curriculum IDs and original criteria stable for historical records.
  The curriculum is reference material, not a fixed recommendation list or required progress.
  New tasks use the shared recommendation schema and immutable generated conditions.
- Same-day success, later retention, and transfer are distinct observations.
- Do not represent coverage as a percentage of total jazz mastery or polygon area.
- Keep runtime dependencies small. The web UI uses a loopback-only Python standard-library
  server. Recommendations use local Codex CLI authentication; no separate API key is required.
  Codex returns structured recommendations; the app validates and writes records.
  Test real connections only with synthetic context, never production personal data.
- If code/curriculum/coach instructions change after release, use a new version.

## Checks

Run `uv run python -m unittest discover -s tests -v` and
`uv run python review.py validate-curriculum` before publishing. Add meaningful
tests for scoring, history, prerequisites, and release boundaries when changing
those behaviors. Do not use sample performance records as user evidence.
