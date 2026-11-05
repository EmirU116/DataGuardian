# Skill candidates

The log of repeated tasks that might become skills (see `docs/skills.md`). `skill-scout` and Claude add candidates here; the user decides.

**Status values:**
- `proposed`: waiting for the user;
- `approved`: the user said yes, and Claude will create it;
- `created`: it exists in `.claude/skills/`;
- `rejected`: the user said no; the reason is recorded, and it won't be proposed again.

last_scanned: 2026-11-05 (first skill-scout run; 4 sessions, 27 commits)

| Candidate | Purpose | Evidence | Status | Date |
|---|---|---|---|---|
| `finish-feature` | Run the definition of done: check the branch's PR isn't merged already, tests, commit, `qa-auditor`, fix → re-test → re-QA loop, `pr-creator`, start the watch. | 2 full feature runs plus 4 earlier `commit → pr-creator` runs, across sessions 8c3871e2 and a5b2dd69. QA found issues on both feature branches. Pitfalls: commits pushed to a branch whose PR was already merged (fixed by cherry-picking onto a new branch, PR #4); a branch cut from a stale `main` (always `git pull --ff-only` before `checkout -b`); a new agent not callable until restart (act-as fallback through general-purpose). | proposed | 2026-11-05 |
| `watch-pr` | Watch an open PR's CI and state; on merge clean up, update `main`, run `skill-scout`, continue with the next plan item. | 1 Monitor watch plus 4 post-merge cleanups across 2 sessions; the user had to prompt 3 times after a merge. Pitfall: `gh pr checks <n> --json` is unsupported, and the watch hid the error with `2>/dev/null`. Use `gh pr view <n> --json state,reviewDecision,statusCheckRollup`, and never discard gh's stderr in a watch loop. | proposed | 2026-11-05 |
| `ship-chore` | Ship a chore: update `main`, check every file is chore-eligible, edit, test if config changed, commit, push, poll the `Tests` run on `main` for the new SHA. | 2 runs (732973c, ab70c57) with an identical poll loop; 2 earlier `.md`-only changes went through PRs before the rule existed. Tip: guard scripted text replacements with `assert t.count(old) == 1`. Shares the poll step with `watch-pr`. | proposed | 2026-11-05 |
| `add-agent` | Add a project helper agent: check it against the Agents rules, write `.claude/agents/<name>.md` with minimal tools, register it in `docs/agents.md` and `CLAUDE.md`, ship as a chore. | 4 times across 2 sessions (pr-creator; 4 helpers; qa-auditor; skill-scout). Pitfall, seen twice: "Agent type not found" until the session restarts; fallback is general-purpose with "act as `<name>`, read `.claude/agents/<name>.md`". | proposed | 2026-11-05 |
