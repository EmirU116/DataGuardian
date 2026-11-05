# Skill candidates

The log of repeated tasks that might become skills (see `docs/skills.md`). `skill-scout` and Claude add candidates here; the user decides.

**Status values:**
- `proposed`: waiting for the user;
- `approved`: the user said yes, and Claude will create it;
- `created`: it exists in `.claude/skills/`;
- `rejected`: the user said no; the reason is recorded, and it won't be proposed again.

last_scanned: never

| Candidate | Purpose | Evidence | Status | Date |
|---|---|---|---|---|
| `finish-feature` | Run the definition of done: tests, commit, `qa-auditor`, fix loop, `pr-creator`, watch. | Run 3 times in session a5b2dd69 (CI workflow, loader fix ×2). QA found blockers and majors twice, so the fix → re-test → re-QA loop matters. | proposed | 2026-11-05 |
| `watch-pr` | Watch an open PR's CI and state, then on merge clean up, update `main` and continue with the next plan item. | Used for PRs #6 and onward. Pitfall: `gh pr checks <n> --json` isn't supported by the installed `gh`, so the first watch never reported CI results. `gh pr view <n> --json state,reviewDecision,statusCheckRollup` works. | proposed | 2026-11-05 |
| `ship-chore` | Ship a chore: update `main`, edit, test if config changed, commit, push, check the `Tests` run on `main`. | New rule (2026-11-05); every `.md` change will follow it. | proposed | 2026-11-05 |
