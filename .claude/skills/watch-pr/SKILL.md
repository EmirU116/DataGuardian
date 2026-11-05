---
name: watch-pr
description: Watch an open pull request's CI checks and merge state in the background, fix CI failures, and after the merge clean up, update main, run skill-scout and start the next plan item. Use right after a PR is opened, or when the user says "watch the PR", "tell me when it's merged" or "continue after merge".
---

# Watch a PR and continue after the merge

Implements the "After a PR is opened" routine in `CLAUDE.md`, with commands that are known to work with the installed `gh`.

## When to use
- Right after `pr-creator` (or the `finish-feature` skill) opens a PR.
- When the user asks to watch a PR, or to continue once it's merged.

## Steps
1. **Start a background watch** with the Monitor tool (`timeout_ms` 1800000; re-arm it when it expires). The script reports only changes, and exits when the PR is merged or closed:
   ```bash
   cd <project root>
   prev=""
   while true; do
     cur=$(gh pr view <n> --json state,reviewDecision,statusCheckRollup \
       --jq '"state=\(.state) review=\(.reviewDecision) checks=" + ([.statusCheckRollup[] | "\(.name):\(.status)/\(.conclusion)"] | join(","))' 2>&1)
     [ "$cur" != "$prev" ] && echo "PR <n> $cur" && prev=$cur
     case "$cur" in *state=MERGED*|*state=CLOSED*) exit 0;; esac
     sleep 60
   done
   ```
2. **CI failed** (`pytest:COMPLETED/FAILURE`): read the log with `gh run view <run-id> --log-failed`. Fix on the same branch, run the tests locally, then commit and push. The watch picks up the new run.
3. **Changes requested** (`review=CHANGES_REQUESTED`) or **closed without merging**: stop and ask the user. Don't continue to the next item.
4. **Merged:**
   ```bash
   git checkout main && git pull --ff-only && git fetch --prune
   git branch -d <branch>
   gh run list --branch main --limit 1 --json status,conclusion   # the post-merge Tests run
   ```
   - If the `main` run fails, fix it before starting anything new.
   - The remote branch is usually deleted by GitHub automatically. If `git ls-remote --heads origin <branch>` still lists it, use the `branch-cleaner` agent.
5. **Look for skill candidates.** Run the `skill-scout` agent, add its new candidates to `docs/skill-candidates.md` as `proposed`, and update `last_scanned`. Ship that as a chore, then post the candidates to the user without waiting for an answer.
6. **Next item.** Take the next entry in the current phase plan's "Suggested branch order" (e.g. `docs/phase-1-plan.md`):
   - create its branch from the fresh `main`;
   - start with its plan, and take it through the definition of done (`finish-feature`).
   
   If the plan has no next item, stop and report that the phase is done.

## Pitfalls
- **`gh pr checks <n> --json` doesn't work here** ("unknown flag: --json"). Use `gh pr view <n> --json statusCheckRollup`.
- **Never hide `gh` errors in a watch loop** (`2>/dev/null || true`). That is how the first watch stayed silent while CI had already passed. Keep stderr in the output, as above.
- **`git branch -d` may warn** "merged to refs/remotes/origin/…, but not yet merged to HEAD" when run before `main` is updated. Update `main` first; once `gh` shows `MERGED`, the warning is harmless.
- **The watch only lives as long as this Claude Code session.** Tell the user if the session is about to end with a PR still open.

## Done when
- The watch has exited on `MERGED`, the local branch is gone, `main` is up to date and its `Tests` run passed.
- `skill-scout` has run, and the next item is started, or the phase is reported done.
