# Tasks: add-parallel-git-workflow

## 1. Worktree Bootstrap

- [x]1.1 Create worktree bootstrap script
  **Dependencies**: None
  **Files**: `scripts/worktree-bootstrap.sh`
  **Traces**: REQ-WTBOOT-2, REQ-WTBOOT-3, REQ-WTBOOT-4, REQ-WTBOOT-5, REQ-WTBOOT-6, REQ-WTBOOT-7, REQ-WTBOOT-9, REQ-WTBOOT-10
  **Details**: Create `scripts/worktree-bootstrap.sh` that accepts `WORKTREE_PATH` and `MAIN_REPO` as arguments. Copies `.env` and `.secrets.yaml` from main repo, runs `uv sync` in both Python project directories, runs skills install. Uses `UV_CACHE_DIR` pointing to `$MAIN_REPO/.uv-cache/`. Reports errors but exits 0 (non-fatal). Must be idempotent.

- [x]1.2 Integrate bootstrap into worktree.py setup
  **Dependencies**: 1.1
  **Files**: `scripts/worktree.py`
  **Traces**: REQ-WTBOOT-1, REQ-WTBOOT-8
  **Details**: After successful worktree creation in `cmd_setup()`, call `scripts/worktree-bootstrap.sh` with the worktree path and main repo path. Add `--no-bootstrap` CLI flag. Output `BOOTSTRAPPED=true|false` in the KEY=VALUE output.

- [x]1.3 Add `.uv-cache/` to `.gitignore`
  **Dependencies**: None
  **Files**: `.gitignore`
  **Traces**: REQ-WTBOOT-7
  **Details**: Add `.uv-cache/` entry to the gitignore file.

## 2. Git Parallel Configuration

- [x]2.1 Create git parallel setup script
  **Dependencies**: None
  **Files**: `scripts/git-parallel-setup.sh`
  **Traces**: REQ-GITCFG-1, REQ-GITCFG-2, REQ-GITCFG-3, REQ-GITCFG-4, REQ-GITCFG-5
  **Details**: Create `scripts/git-parallel-setup.sh` that configures the local repo (not global) with rerere, zdiff3, histogram diff, and updateRefs. Script should be idempotent and print what it configured. Uses `git config --local` for all settings.

- [x]2.2 Create `.gitattributes` with merge strategies
  **Dependencies**: None
  **Files**: `.gitattributes`
  **Traces**: REQ-GITCFG-6
  **Details**: Create `.gitattributes` defining merge strategies for auto-generated files: `uv.lock` with `merge=union`, lock files with `merge=binary`. Keep it minimal — only files that genuinely benefit from custom merge behavior.

- [x]2.3 Add `git-setup` target to agent-coordinator Makefile
  **Dependencies**: 2.1
  **Files**: `agent-coordinator/Makefile`
  **Traces**: REQ-GITCFG-1, REQ-GITCFG-2, REQ-GITCFG-3, REQ-GITCFG-4
  **Details**: Add a `make git-setup` target that runs `scripts/git-parallel-setup.sh` from the repo root.

## 3. GitHub Merge Queue + CI

- [x]3.1 Add `merge_group` trigger to CI workflow
  **Dependencies**: None
  **Files**: `.github/workflows/ci.yml`
  **Traces**: REQ-MQ-1
  **Details**: Add `merge_group:` to the `on:` triggers in CI. This allows GitHub's merge queue to run CI on combined PR state before merging.

- [x]3.2 Update parallel-cleanup-feature to prefer merge queue
  **Dependencies**: None
  **Files**: `skills/parallel-cleanup-feature/SKILL.md`
  **Traces**: REQ-MQ-2
  **Details**: In the merge step, add guidance to check if merge queue is enabled (`gh repo view --json mergeCommitAllowed`) and prefer `gh pr merge --merge-queue` over direct merge.

- [x]3.3 Update merge_pr.py to default to merge queue
  **Dependencies**: None
  **Files**: `skills/merge-pull-requests/scripts/merge_pr.py`
  **Traces**: REQ-MQ-3
  **Details**: In `_try_merge()`, proactively check if the repo has merge queue enabled and use `--merge-queue` by default rather than falling back to it only on error. Keep the existing fallback path for repos without merge queue.

## 4. Documentation

- [x]4.1 Create parallel git config documentation
  **Dependencies**: 2.1, 3.1
  **Files**: `docs/parallel-git-config.md`
  **Traces**: REQ-GITCFG-1, REQ-GITCFG-2, REQ-GITCFG-3, REQ-GITCFG-4, REQ-MQ-1
  **Details**: Document: (1) what the git-parallel-setup.sh script configures and why, (2) how to enable GitHub merge queue in branch protection settings, (3) how rerere helps with recurring conflicts across worktrees, (4) how to verify the configuration is active.

## Parallel Execution Plan

**Group A** (independent, run concurrently): 1.1, 1.3, 2.1, 2.2, 3.1, 3.2, 3.3
**Group B** (depends on Group A): 1.2 (needs 1.1), 2.3 (needs 2.1)
**Group C** (depends on Group B): 4.1 (needs 2.1, 3.1)

Maximum parallel width: 7 tasks in Group A.
