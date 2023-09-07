# whl2conda 

[![pypi version](https://img.shields.io/pypi/v/whl2conda.svg)](https://pypi.org/project/whl2conda/)
[![conda version](https://img.shields.io/conda/vn/conda-forge/whl2conda)](https://anaconda.org/conda-forge/whl2conda)
[![documentation](https://img.shields.io/badge/docs-mkdocs%20material-blue.svg?style=flat)](https://zuzukin.github.io/whl2conda/)  
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/whl2conda)
![GitHub](https://img.shields.io/github/license/analog-cbarber/whl2conda)  
[![CI](https://github.com/zuzukin/whl2conda/actions/workflows/python-package-conda.yml/badge.svg)](https://github.com/zuzukin/whl2conda/actions/workflows/python-package-conda.yml)
![GitHub issues](https://img.shields.io/github/issues/analog-cbarber/whl2conda)

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
