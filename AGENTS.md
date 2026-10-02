# Agent Instructions

## Repository

- Upstream: `TTLucian/ha-climate-react`
- All PRs target upstream `main`
- Component path: `custom_components/climate_react/` (underscore, not
  `climate-react`)
- Platform files: `__init__.py`, `climate_react.py` (the climate entity),
  `config_flow.py`, `const.py`, `diagnostics.py`, plus the `number.py`,
  `select.py` and `switch.py` platforms and a `brand/` directory.
- This integration registers **no services**.

## Branching

- Never commit directly to `main`
- Branch prefixes: `fix/` bugfixes, `feat/` features, `analysis/` research,
  `chore/` tooling and CI, `release/` version prep
- Rebase on latest `upstream/main` before pushing
- Confirm the branch before editing - `git rev-parse --abbrev-ref HEAD`. A
  `git checkout <branch> -- <paths>` in a compound command can leave you
  somewhere you did not intend.

## Pull Requests

- Always create PRs as **drafts** first
- One concern per PR - keep scope tight
- Draft -> ready fires `ready_for_review`; CI is configured to run on it

## Toolchain - uv, and the lockfile is the contract

`uv.lock` is the single source of truth. `--locked` matches CI: the committed
lockfile is exactly what gets tested.

```bash
uv sync --locked          # install; there is no "test" group, "dev" is default
uv run ruff check .
uv run ruff format --check .
uv run mypy --namespace-packages --explicit-package-bases \
  custom_components/climate_react tests/ .github/scripts/
uv run pytest
```

- `uv sync --group test` **fails** here - the group is named `dev`.
- `mypy` reads `pyproject.toml`. There is no `mypy.ini`; the two used to coexist
  and `mypy.ini` silently won, leaving the `pyproject.toml` settings dead.
- Never pass `--follow-imports=skip` to mypy. It reports false
  `untyped-decorator` errors on `@pytest.mark.asyncio` because it cannot see
  pytest's own types. The flags above are the ones that work.
- Do not use **black**. `ruff format` is the configured formatter; one
  formatter is easier to keep consistent than two. (An earlier note in this
  file family claimed black corrupts `except (A, B):`. That is wrong on
  Python 3.14 - `except A, B:` parses as a tuple and is valid.)

## Testing

- Tests import the integration from the repository root. `tests/` has no
  `__init__.py`, so pytest's rootdir insertion adds only `tests/` itself.
  The fix is `pythonpath = ["."]` in `[tool.pytest.ini_options]` - do **not**
  replace it with a `sys.path` hack in `conftest.py`, which would put imports
  after code and trip ruff's `E402`.
- Fix test failures before pushing - no PRs with known failing tests
- CI runs `pytest -q --junitxml=junit.xml` and uploads the report as an artifact
- There is **no coverage gate**. Do not add `--cov-fail-under`: a gate that
  fails every run teaches people to ignore it. `pytest-cov` is already in the
  lockfile if coverage needs measuring.

## Workflows

Two guards exist because a bad workflow reference fails *silently*:

- `.github/scripts/validate_workflow_actions.py` - fetches each SHA-pinned
  action's `action.yml` and fails on an unresolvable reference or a `with:` key
  the action does not declare. GitHub **ignores unknown `with:` keys**, so a
  typo there looks like a passing job.
- `.github/workflows/actionlint.yml` - syntax and expression checking, including
  shellcheck rules, via the `rhysd/actionlint` container.

Both have caught real bugs here. When adding a workflow step, check the action's
real input names - do not copy them from `actions/setup-python` onto a different
action.

## Pre-commit (optional)

`.pre-commit-config.yaml` mirrors CI: ruff, ruff-format, mypy and actionlint on
commit, `uv lock --check` when the lockfile or `pyproject.toml` changes, and
pytest on pre-push. Keep the pinned `rev`s equal to the tool versions in
`pyproject.toml`/`uv.lock`, and the `files:` scope equal to what CI checks - a
hook that checks less than CI reads as a passing check while checking nothing.

The actionlint hook is `actionlint-docker`, pinned to the same image CI uses. It
needs Docker, and for a reason: plain actionlint silently skips every shellcheck
rule when shellcheck is absent locally, which is how unquoted `$GITHUB_OUTPUT`
redirections reach CI.

The mypy hook needs `--namespace-packages --explicit-package-bases`. Without
them it fails outright with "Source file found twice under different module
names", because it hands mypy individual file paths.

```bash
uv sync --locked && uv run pre-commit install
```

## Line endings - this repository is MIXED

Most files are LF, but these six are CRLF:

- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/workflows/release-drafter.yml`
- `custom_components/climate_react/const.py`
- `custom_components/climate_react/diagnostics.py`
- `custom_components/climate_react/number.py`
- `custom_components/climate_react/select.py`

`tests/` and `manifest.json`/`strings.json`/`translations/en.json` are LF here.
Repositories in this family have used CRLF, so do not assume one convention.
When scripting a bulk edit, preserve each file's existing endings
and check `git diff --stat` before committing - a one-line change that flips
endings becomes a whole-file diff.

## JSON files - edit, never re-serialize

Do not read a repo JSON file with `json.load` and write it back with `json.dump`.
`manifest.json`, `strings.json` and `translations/en.json` use hand-set 2-space
indentation; a serializer round-trip rewrites every line, producing an enormous
diff for a one-key change.

Edit the specific line with the editor tool or a targeted `sed`. If a bulk edit
is genuinely needed, verify with `git diff --stat` that the change is
proportional - check the stat *before* committing, not after.

## Translations

- `custom_components/climate_react/translations/en.json` is the only
  translation file in this repository, and it is the source of truth.
- New UI strings go in `strings.json` **and** `translations/en.json`. Both are
  required; a key present in only one shows up untranslated in the UI.
- There is no translation script here. Do not add one by copying it from
  another repository.

## Releases

- A release needs `release_notes/RELEASE_NOTES_vX.Y.Z.md`; there is no
  `release_notes/` directory yet, so create it with the first one.
- Prerelease versions (containing `-`) are skipped by the workflow and
  published by hand via the API.
- Bump `manifest.json` by editing the one `version` line, then tag only after
  the release merge lands on `main`.
- The drafter attaches `climate_react.zip` and updates an existing draft rather
  than skipping it.

## Home Assistant version pinning

`uv.lock` pins Home Assistant to a **stable** release (`2026.9.4`), which is what
most users run. That is a deliberate, per-repository choice: repositories
sharing this tooling lock different versions, so read `uv.lock` rather than
assuming a shared value.

You do not choose the Home Assistant version directly. The test harness pins it
with `==`, and there is one harness release per Home Assistant release:

```
0.13.354 -> 2026.8.0     0.13.363 -> 2026.9.0    0.13.367 -> 2026.9.4
0.13.358 -> 2026.9.0b0   0.13.365 -> 2026.9.2    0.13.368 -> 2026.10.0b0
```

So to move Home Assistant you move the harness, and the newest harness is not
always what you want - `0.13.368` pins a **pre-release**. To land on a specific
stable Home Assistant, pin the harness that ships it:

```bash
uv lock --upgrade-package 'pytest-homeassistant-custom-component==0.13.367'
```

`requires-python` must stay `>=3.14.2,<3.15`. A looser bound makes uv keep a
second, much older homeassistant entry in the lockfile for 3.14.0/3.14.1
markers, which silently pins CI to a version nobody runs.

CI tests what the lockfile says, not what users run, so the lock is refreshed
deliberately rather than on every release. The weekly `Dependency freshness`
job (`.github/scripts/check_dependency_freshness.py`) compares the locked
`homeassistant` against the newest stable, and only calls the harness stale
when upgrading it would stay on stable Home Assistant. It runs on schedule and
manual dispatch only, not on every push.

## Files to never commit

- `*.log`
- `*.txt` used as script output
- `junit.xml` (CI artifact)
- `__pycache__/`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `.coverage`
- `pyrightconfig.local.json` - but `pyrightconfig.json` **is** tracked, because
  without an explicit `pythonVersion` Pylance falls back to an older
  interpreter and reports errors that do not exist
- `.vscode/` is **tracked** on purpose - see `.gitignore`. Only
  `.vscode/*.local.json` stays local.
