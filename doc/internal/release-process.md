# whl2conda release process

The release process is currently entirely manual:

## Prerequistes

* [ ] Tests should be added for all new features or changed behavior.
* [ ] All tests must pass locally and in CI jobs.
* [ ] Significant changes should be described in `CHANGELOG.md`
* [ ] New features and changes must be documented.

## Release procedure

1. Update version in `src/whl2conda/VERSION`.

    We use calver scheme of the form `YY.M.<patch>`, so the first release
    in June 2024 would be `24.6.0`. Increment the last number if there already
    was a release in the month. It may be surprising to users to see signficant
    changes introduced in a patch release, so it probably is best to delay such
    releases to the next month.

2. Update the checked in copy of the standard renames table:

    ```bash
    $ make update-std-rename
    ```
   
    commit the changed `src/whl2conda/api/stdrename.json` file.

3. After all changes have been merged, check out `main` branch.

4. Build wheel and conda package

    ```bash
    $ make build-wheel
    ```
5. Test built packages (*optional but recommended*)

    Test the generated wheel and conda package by installing locally and
    testing manually or by running `pytest test` in environment with installed
    package.

6. When everything is ok, upload to pypi:

    ```bash
    $ make check-upload
    $ make upload
    ```

    This assumes that you have permission to upload and have configured a token
    in you `~/.pypirc`.

7. Watch for and accept merge request from conda-forge

    Sometime after the pypi upload, the whl2conda-feedstock on conda-forge
    will get an automatically generated merge request, and feedstock maintainers
    will get a notification. Usually this happens within a day of the pypi upload. 

    If there are no breaking runtime dependencies, then nothing needs to be done
    other than to accept the merge request. If dependencies have changed, it will
    be necesssary to update the feedstock's conda-recipe.

