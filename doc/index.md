**Generate conda packages directly from pure python wheels**

*whl2conda* is a command line utility for building and testing 
conda packages generated directly from pure python wheels.

## Features

* **Performance**: because it does not need to create conda environments
    in order to build, this is *much* faster than solutions involving *conda-build*.

* **Dependency renaming**: renames pypi package dependencies to their 
    corresponding conda name. Automatically renames packages from known
    list collected from conda-forge and supports user-specified rename
    patterns as well.

* **Multiple package formats**: can generate both V1 ('.tar.bz2') and V2 ('.conda')
    conda package formats. Can also generate a unpacked directory tree for debugging
    or additional user customization.

* **Project configuration**: *whl2conda* project-specific options can be read from
    project's `pyproject.toml` file.

* **Test install support**: supports installing conda package into a conda
    environment for testing prior to deployment.

* **Hides pypi dependencies**: rewrites the original pip/pypi dependencies in the
    installed dist-info to avoid [compatibility issues](guide/renaming.md#hide-pip).



