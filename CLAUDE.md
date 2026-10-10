# CLAUDE.md

Read `BRIEF.md` first — it is the specification. `docs/BUILD_PLAN.md` says how it is being
built and what was decided along the way.

## Rules that are easy to break
- **This repo is public.** Nothing private goes in it: no article text, no evidence quotes,
  no rejected items, no official files as received, no keys. Those go to `private/`
  (gitignored; a separate private repo in CI).
- **Brand-neutral.** No sponsor name anywhere — code, copy, tokens, commit messages, repo name.
  Commits use the GitHub no-reply address set in this repo's local git config.
- **No personal names, ever** — not in records, not in evidence, not in fixtures or tests.
- **Arabic, French and English UI strings live in `site/src/i18n/*.json`**, never in code.
- **Every public number traces to one file** in `data/published/`.
- **Label assumptions.** Any threshold, window or default that was chosen, not measured,
  says so where it is defined, with its value and why.
- Work task by task (BRIEF §10). Each task ends on its "done" test, passing in CI.
- Nobody pushes straight to `main` once the scaffold is merged: branch, pull request, green CI.
