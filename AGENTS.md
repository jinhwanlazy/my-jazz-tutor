# My Jazz Tutor workspace

This directory is one Git monorepo with two work areas and distinct roles.
The Git root is this directory; do not initialize nested repositories.

- `practice/`: daily coaching, user-reported practice records, and generated reports.
- `workflow/`: development of the coaching rules, curriculum, tools, and Git releases.

Read the selected work area's `AGENTS.md` before working. Choose the area from the
user's intent. A practice discussion must not silently become workflow development.
An explicit setup or migration request may cover both areas. Do not launch
additional agents or sessions merely to split these roles.

Read the user's experience, goals, and preferences from the local
`practice/profile.json`. The example profile contains defaults, not user evidence.
Do not invent practice history or a mastery deadline. Personal records, profiles,
MIDI sessions, and coaching notes stay local and must not be force-added to Git.
Git commits and tags retain runtime history. `practice/.runtime/` is a disposable
cache; `practice/runtime.json` pins the local active commit and stays untracked.
