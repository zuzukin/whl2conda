# Release Procedure

This document describes the steps to create a new release of whl2conda.

Releases are automated (#145): pushing a `vYY.M.patch` tag triggers the
[release workflow](.github/workflows/release.yml), which builds the wheel,
sdist, and conda package, publishes the wheel and sdist to PyPI, creates a
GitHub release with notes taken from the changelog and the conda package
attached, and deploys the versioned documentation to GitHub Pages.

## One-time setup: PyPI trusted publisher

The workflow authenticates to PyPI with [Trusted
Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) — no API token
secret is stored in the repository. This requires a one-time configuration in
the [whl2conda project settings on PyPI](https://pypi.org/manage/project/whl2conda/settings/publishing/):

- Owner: `zuzukin`, repository: `whl2conda`
- Workflow name: `release.yml`
- Environment name: `pypi`

A matching `pypi` environment should also exist in the GitHub repository
settings (Settings → Environments); it may optionally restrict deployments
to `v*` tags.

## Versioning

whl2conda uses calendar versioning (CalVer) in the format `YY.M.patch`:
- `YY` - two-digit year
- `M` - month (no leading zero)
- `patch` - patch number within the month (starts at 0)

The version is stored in `src/whl2conda/VERSION` and read by hatchling at build time.

## Pre-release Checklist

### 1. Prepare the release branch

Ensure all changes for the release are merged to `main`. Create a release branch
if needed:

```bash
git checkout main
git pull
git checkout -b release/YY.M.patch
```

### 2. Update the version

Edit `src/whl2conda/VERSION` to contain the new version number.

### 3. Update the changelog

Edit `CHANGELOG.md`:
- Replace `*in progress*` with the release date in the current version header
- Ensure all notable changes are documented under the appropriate sections
  (Features, Bug fixes, Changes, Development)
- Add a new `## [next version] - *in progress*` section at the top for future changes

### 4. Update standard renames

Update the standard package rename mappings from conda-forge:

```bash
pixi run update-stdrename
```

Review the changes and commit if there are updates.

### 5. Run the full test suite

```bash
pixi run test
pixi run lint
pixi run typecheck
```

Ensure all tests pass on the current branch. CI should also pass on all platforms.

### 6. Commit and merge to main

```bash
git add src/whl2conda/VERSION CHANGELOG.md src/whl2conda/api/stdrename.json
git commit -m "Release YY.M.patch"
git push origin release/YY.M.patch
```

Create a PR from the release branch to `main`, wait for CI to pass, and merge it.

## Publish

### 7. Push the release tag

Tag the release commit on `main` and push the tag:

```bash
git checkout main
git pull
git tag vYY.M.patch
git push origin vYY.M.patch
```

This triggers the [release workflow](.github/workflows/release.yml), which:

1. Builds the wheel, sdist, and conda package, verifying that the tag
   matches `src/whl2conda/VERSION`
2. Publishes the wheel and sdist to PyPI
3. Creates a GitHub release titled with the tag, using the matching
   `CHANGELOG.md` section as notes, with the built packages attached
4. Deploys the versioned documentation to gh-pages using mike

Watch the workflow at the [actions page](https://github.com/zuzukin/whl2conda/actions)
(or `gh run watch`), then verify:

- The new version appears on [PyPI](https://pypi.org/project/whl2conda/)
- The [GitHub release](https://github.com/zuzukin/whl2conda/releases) looks right
- The [documentation site](https://zuzukin.github.io/whl2conda/) shows the new version

The build job can be exercised without releasing by running the workflow
manually from the actions page (`workflow_dispatch`); publishing only happens
on version tags.

## Post-release

### 8. conda-forge update

The [whl2conda-feedstock](https://github.com/conda-forge/whl2conda-feedstock)
should automatically detect the new PyPI release and open a PR to update the
conda-forge package. Review and merge that PR.

### 9. Prepare for next development cycle

Update `src/whl2conda/VERSION` on `main` to the next expected version and add
a new changelog section if not already present.

## Pixi Tasks Reference

| Task | Description |
|------|-------------|
| `pixi run build` | Build wheel, sdist, and conda package |
| `pixi run build-sdist` | Build source distribution only |
| `pixi run build-conda` | Build conda package from wheel |
| `pixi run check-upload` | Verify packages with twine |
| `pixi run upload` | Upload wheel and sdist to PyPI |
| `pixi run upload-wheel` | Upload only the latest wheel |
| `pixi run upload-sdist` | Upload only the latest sdist |
| `pixi run update-stdrename` | Update standard rename mappings |
| `pixi run doc-deploy` | Deploy docs to gh-pages |
| `pixi run doc-push` | Push gh-pages to GitHub |
| `pixi run clean-build` | Remove build artifacts |
