# Release Procedure

This document describes the steps to create a new release of whl2conda.

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

### 6. Build packages

Clean any previous build artifacts and build fresh:

```bash
pixi run clean-build
pixi run build
```

This builds both the wheel/sdist and the conda package.

### 7. Verify packages

Check that packages are well-formed:

```bash
pixi run check-upload
```

Optionally, test the conda package locally:

```bash
conda create -n test-whl2conda dist/*.conda
conda activate test-whl2conda
whl2conda --version
whl2conda convert --help
```

### 8. Commit and tag

```bash
git add src/whl2conda/VERSION CHANGELOG.md src/whl2conda/api/stdrename.json
git commit -m "Release YY.M.patch"
git tag vYY.M.patch
```

### 9. Push and verify CI

```bash
git push origin release/YY.M.patch
git push origin vYY.M.patch
```

Wait for CI to pass on the release branch.

## Publish

### 10. Upload to PyPI

```bash
pixi run upload
```

This runs `twine check` and then uploads the wheel and sdist to PyPI.

### 11. Create GitHub release

Go to the [GitHub releases page](https://github.com/zuzukin/whl2conda/releases)
and create a new release from the tag. Copy the relevant changelog entries into
the release notes.

### 12. Deploy documentation

```bash
pixi run doc-deploy
pixi run doc-push
```

### 13. Merge to main

Create a PR from the release branch to `main` and merge it.

## Post-release

### 14. conda-forge update

The [whl2conda-feedstock](https://github.com/conda-forge/whl2conda-feedstock)
should automatically detect the new PyPI release and open a PR to update the
conda-forge package. Review and merge that PR.

### 15. Prepare for next development cycle

After merging, update `src/whl2conda/VERSION` on `main` to the next expected
version and add a new changelog section if not already present.

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
