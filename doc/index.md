**Generate conda packages directly from pure python wheels**

*whl2conda* is a command line utility to build and test conda packages
generated directly from pure python wheels.

## Features

* **Performance**: because it does not need to create conda environments
    for building, this is much faster than solutions involving *conda-build*.

* **Multiple package formats**: can generate both V1 ('.tar.bz2') and V2 ('.conda')
    conda package formats. Can also generate a unpacked directory tree for debugging
    or additional user customization.

* **Dependency renaming**: renames pypi package dependencies to their 
    corresponding conda name. Automatically renames packages from known
    list collected from conda-forge and supports user-specified rename
    patterns as well.

* **Project configuration**: project-specific options can be saved in
    project's `pyproject.toml` file.

* **Install support**: supports installing conda package into a conda
    environment for testing prior to deployment.

* **Hides pypi dependencies**: if the original pypi dependencies are included in
    the python dist-info included in the conda package, this can result in 
    problems if pip or other python packaging tools are used in the conda environment.
    To avoid this, *whl2conda* changes these dependencies to extras.

