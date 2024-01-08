# whl2conda 

[![pypi version](https://img.shields.io/pypi/v/whl2conda.svg)](https://pypi.org/project/whl2conda/)
[![conda version](https://img.shields.io/conda/vn/conda-forge/whl2conda)](https://anaconda.org/conda-forge/whl2conda)
[![documentation](https://img.shields.io/badge/docs-mkdocs%20material-blue.svg?style=flat)](https://zuzukin.github.io/whl2conda/)  
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/whl2conda)
![GitHub](https://img.shields.io/github/license/analog-cbarber/whl2conda)  
[![CI](https://github.com/zuzukin/whl2conda/actions/workflows/python-package-conda.yml/badge.svg)](https://github.com/zuzukin/whl2conda/actions/workflows/python-package-conda.yml) [![codecov](https://codecov.io/gh/zuzukin/whl2conda/graph/badge.svg?token=097C3MBNIX)](https://codecov.io/gh/zuzukin/whl2conda)
![GitHub issues](https://img.shields.io/github/issues/analog-cbarber/whl2conda)


**Generate conda packages directly from pure python wheels**

*whl2conda* is a command line utility to build and test conda packages
generated directly from pure python wheels.

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
    installed dist-info to avoid [compatibility issues](https://zuzukin.github.io/whl2conda/latest/guide/renaming.html#hide-pip).


## Installation

With pip:

```bash
pip install whl2conda
```

With conda (upcoming):

```bash
conda install -c conda-forge whl2conda
```

## Quick usage

Generate a conda package in same directory as wheel file:

```bash
whl2conda build dist/mypackage-1.2.3-py3-none-any.whl
```

Add default tool options to `pyproject.toml`

```bash
whl2conda config --generate-pyproject pyproject.toml
```
Build both wheel and conda package for project:

```bash
whl2conda build --build-wheel my-project-root
```

Create python 3.10 test environment for generated conda package:

```bash
whl2conda install dist/mypackage-1.2.3.-py_0.conda --create -n testenv \
  --extra pytest python=3.10
```
