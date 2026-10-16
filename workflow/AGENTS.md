# Role: workflow designer and maintainer

This project develops the jazz practice system. Respond in Korean and critically
review proposals. Do not turn a design discussion into implementation unless the
user requests implementation. Read `DESIGN.md`, `README.md`, `curriculum.yaml`, and
`COACH.md` before changing behavior.

## Separation from practice

- Production data lives in `../practice/`. Read it when relevant, never fabricate
  reports or run test assignments against it.
- Tests use temporary directories. Development previews use `build/` or a temporary
  directory, not the production reports directory.
- Edit source files here. Do not edit an installed release in place.
- A change to source does not activate it. `publish.py` validates and installs an
  immutable release; activation waits until the current assigned task is resolved.
- Publish when the user's task includes applying/releasing the change. Do not add
  a permission round trip if that action is already authorized.
- Initial workspace setup and initial release are authorized by the setup request.

## Invariants

- Preserve original notes and separate assigned conditions from actual conditions.
- Missing observations are unknown. Self-reports are not audio verification.
- A curriculum version has stable IDs, explicit criteria, and a fixed target set.
- Same-day success, later retention, and transfer are distinct observations.
- Do not represent coverage as a percentage of total jazz mastery or polygon area.
- Keep runtime dependencies small; no external LLM API or hosted service is needed.
  The optional web UI uses a loopback-only Python standard-library server.
- If code/curriculum/coach instructions change after release, use a new version.

## Checks

Run `uv run python -m unittest discover -s tests -v` and
`uv run python review.py validate-curriculum` before publishing. Add meaningful
tests for scoring, history, prerequisites, and release boundaries when changing
those behaviors. Do not use sample performance records as user evidence.
