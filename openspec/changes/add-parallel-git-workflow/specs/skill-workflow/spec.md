# skill-workflow Delta: add-parallel-git-workflow

## ADDED Requirements

### Requirement: Worktree Bootstrap on Setup

`worktree.py setup` SHALL call a bootstrap script after creating a new worktree, copying environment files and installing dependencies so the worktree is immediately runnable. Bootstrap failures SHALL be non-fatal. A `--no-bootstrap` flag SHALL skip bootstrapping.

- **GIVEN** a main repo with `.env` and Python project directories
- **WHEN** `python3 scripts/worktree.py setup <change-id>` completes
- **THEN** the bootstrap script SHALL copy `.env` and `.secrets.yaml` from the main repo to the worktree
- **AND** run `uv sync --all-extras` in `agent-coordinator/` within the worktree
- **AND** run `uv sync` in `scripts/` within the worktree
- **AND** run `skills/install.sh --mode rsync --force --deps none --python-tools none`
- **AND** set `UV_CACHE_DIR` to a shared cache location in the main repo
- **AND** output `BOOTSTRAPPED=true` in the KEY=VALUE output

#### Scenario: Worktree is bootstrapped with environment and dependencies

- **GIVEN** a main repo with `.env` and `agent-coordinator/pyproject.toml`
- **WHEN** `python3 scripts/worktree.py setup my-feature` completes
- **THEN** the worktree contains a copy of `.env`
- **AND** `agent-coordinator/.venv/` exists in the worktree
- **AND** the output includes `BOOTSTRAPPED=true`

#### Scenario: Bootstrap skipped with --no-bootstrap flag

- **GIVEN** a main repo with `.env`
- **WHEN** `python3 scripts/worktree.py setup my-feature --no-bootstrap` completes
- **THEN** the worktree does NOT contain `.env`
- **AND** the output includes `BOOTSTRAPPED=false`

#### Scenario: Bootstrap failure is non-fatal

- **GIVEN** a main repo where `uv sync` would fail
- **WHEN** `python3 scripts/worktree.py setup my-feature` completes
- **THEN** the worktree is still created successfully
- **AND** a warning is printed about the bootstrap failure
- **AND** the output includes `BOOTSTRAPPED=false`

### Requirement: Parallel-Friendly Git Configuration Script

`scripts/git-parallel-setup.sh` SHALL configure the local repository with `rerere.enabled=true`, `rerere.autoUpdate=true`, `merge.conflictStyle=zdiff3`, `diff.algorithm=histogram`, and `rebase.updateRefs=true`. The script SHALL be idempotent and use `git config --local` only.

- **GIVEN** a git repository with default configuration
- **WHEN** `bash scripts/git-parallel-setup.sh` is run
- **THEN** all five git configuration values SHALL be set locally
- **AND** the script SHALL print what it configured

#### Scenario: Git parallel config applied to fresh repo

- **GIVEN** a git repository with no custom merge configuration
- **WHEN** `bash scripts/git-parallel-setup.sh` is run
- **THEN** `git config --local rerere.enabled` returns `true`
- **AND** `git config --local merge.conflictStyle` returns `zdiff3`
- **AND** `git config --local diff.algorithm` returns `histogram`
- **AND** `git config --local rebase.updateRefs` returns `true`

#### Scenario: Script is idempotent

- **GIVEN** a repository where `git-parallel-setup.sh` has already been run
- **WHEN** `bash scripts/git-parallel-setup.sh` is run again
- **THEN** all configuration values remain unchanged
- **AND** the script exits successfully

### Requirement: CI Merge Group Trigger

The CI workflow SHALL trigger on `merge_group` events in addition to `push` and `pull_request` so that GitHub's merge queue can validate combined PR state before merging.

- **GIVEN** a PR added to the GitHub merge queue
- **WHEN** GitHub creates a merge_group validation branch
- **THEN** the CI workflow SHALL trigger and run all checks
- **AND** the merge SHALL proceed only if CI passes

#### Scenario: CI runs on merge queue validation

- **GIVEN** a pull request enqueued in the GitHub merge queue
- **WHEN** GitHub fires a `merge_group` event
- **THEN** the CI workflow triggers on the temporary merge branch
- **AND** all test, lint, and validation jobs execute against the combined state
