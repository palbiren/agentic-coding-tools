# Change: add-parallel-git-workflow

## Why

When multiple agents work in parallel worktrees, three systemic problems block productivity: (1) new worktrees lack `.env`, `.secrets.yaml`, and installed dependencies, so agents cannot run code and fall back to main where they create merge conflicts; (2) git is configured with conservative defaults — no rerere (recurring conflicts re-resolved manually), no zdiff3 (conflict markers lack base context), no merge queue (concurrent PR merges can break main); (3) the CI pipeline doesn't trigger on `merge_group` events, so GitHub's merge queue cannot validate combined PR state before merging. These are the three most common failure modes observed in parallel agent development sessions.

## What Changes

### 1. Worktree Bootstrap (`scripts/worktree.py` + `scripts/worktree-bootstrap.sh`)

- Extend `worktree.py setup` to call a post-setup bootstrap script after worktree creation
- New `scripts/worktree-bootstrap.sh` copies `.env` and `.secrets.yaml` from main repo to worktree
- Bootstrap runs `uv sync --all-extras` in `agent-coordinator/` and `uv sync` in `scripts/` within the worktree
- Bootstrap runs `skills/install.sh --mode rsync --force --deps none --python-tools none` to sync skills
- Set `UV_CACHE_DIR` to a shared location (main repo's `.uv-cache/`) so worktrees share the dependency cache instead of downloading separately
- Add `--no-bootstrap` flag to `worktree.py setup` to skip bootstrap when not needed (e.g., doc-only changes)
- Add `.uv-cache/` to `.gitignore`

### 2. Parallel-Friendly Git Configuration (`.gitattributes` + documented `.gitconfig`)

- Add `.gitattributes` with merge strategies for auto-generated files (e.g., `*.lock merge=binary`, `uv.lock merge=union`)
- Create `scripts/git-parallel-setup.sh` that configures the local repo with:
  - `rerere.enabled=true` + `rerere.autoUpdate=true` (share conflict resolutions across worktrees via `.git/rr-cache/`)
  - `merge.conflictStyle=zdiff3` (show base version in conflict markers)
  - `diff.algorithm=histogram` (better diffs for repetitive code patterns)
  - `rebase.updateRefs=true` (automatic stacked branch pointer updates)
- Add `make git-setup` target to `agent-coordinator/Makefile` (and document in root README)
- Document recommended git config in `docs/parallel-git-config.md`

### 3. GitHub Merge Queue + CI Integration

- Add `merge_group` trigger to `.github/workflows/ci.yml` so CI runs on merge queue validation branches
- Document GitHub merge queue enablement steps (branch protection settings) in `docs/parallel-git-config.md`
- Update `skills/parallel-cleanup-feature/SKILL.md` to prefer `gh pr merge --merge-queue` when merge queue is enabled
- Update `skills/merge-pull-requests/scripts/merge_pr.py` to detect merge queue availability and use it by default

## Impact

**Affected specs:**
- `skill-workflow` — worktree setup steps in implement/cleanup skills gain bootstrap behavior
- `docker-lifecycle` — no direct changes, but worktree bootstrap ensures docker-compose works in worktrees

**Architecture layers:**
- **Execution** — worktree bootstrap ensures agents can execute code in worktrees (primary impact)
- **Coordination** — merge queue integration improves merge ordering (secondary impact)

**Major touchpoints:**
- `scripts/worktree.py` — add bootstrap call after worktree creation
- `scripts/worktree-bootstrap.sh` — new file
- `scripts/git-parallel-setup.sh` — new file
- `.github/workflows/ci.yml` — add `merge_group` trigger
- `.gitattributes` — new file with merge strategies
- `.gitignore` — add `.uv-cache/`
- `agent-coordinator/Makefile` — add `git-setup` target
- `skills/parallel-cleanup-feature/SKILL.md` — prefer merge queue
- `skills/merge-pull-requests/scripts/merge_pr.py` — default to merge queue when available
- `docs/parallel-git-config.md` — new documentation

**No breaking changes.** All additions are backward-compatible. `--no-bootstrap` flag preserves existing worktree behavior. Git config changes are local (not committed to `.git/config`). Merge queue is opt-in via GitHub branch protection.
