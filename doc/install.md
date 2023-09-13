
## Using pip

```bash
pip install whl2conda
```

## Using conda

```bash
conda install -c conda-forge whl2conda
```

*whl2conda* does not have a direct runtime dependency on conda, so it
is safe to install in environments other than `base`.

## Prerequisites

It is assumed that you have installed conda, and that it is in the program
path, but it is currently only required for `whl2conda install`. Furthermore,
if you use the `--conda-bld` option, you must have `conda-index` installed
in your base environment (you will already have it if you have `conda-build`).

