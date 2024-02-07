## Overview

Python packages found on [pypi.org] and installed using [pip][pip-install]
often have the same name as packages found on [anaconda.org] and installed
using [conda]. For instance, you can install `pylint` using:

=== "pip"

    ```bash
    $ pip install pylint
    ```

=== "conda"

    ```bash
    $ conda install -c conda-forge pylint
    ```

However, pip and conda use totally separate packaging systems and there
is no inherent requirement that package names match between the two, and 
indeed there are quite a few exceptions, for example:

=== "pip"

    ```bash
    $ pip install numpy-quaternion 
    $ pip install tables
    $ pip install torch
    ```

=== "conda"

    ```bash
    $ conda install -c conda-forge quaternion 
    $ conda install -c conda-forge pytables
    $ conda install -c conda-forge pytorch
    ```

So when converting from wheels to conda packages, it is important that
these differences be handled by the tool.

## Standard renames

The *whl2conda* tool maintains a table of automatic renaming rules that
is taken from mappings collected automatically from tools supporting the
public [conda-forge] repository. *whl2conda* includes a static copy of
this table collated when the *whl2conda* package was built, but also 
supports the ability to maintain and update a locally cached copy dynamically. If
there is package new to [conda-forge] that may have appeared since installing
*whl2conda*, you can update your local cache using:

```bash
$ whl2conda --update-std-renames
```

The cache file is kept in a location in your user directory that is specific 
to your operating system:

* Linux: `~/.cache/whl2conda/stdrename.json`
* MacOS: `~/Library/Caches/whl2conda/stdrename.json`
* Windows: `~\AppData\Local\whl2conda\Cache\stdrename.json`

This file is simply a JSON dictionary mapping pypi names to conda names.

If you want to generate a copy of this file in another location (e.g.
for use by other development tools), you can add a path to the
`---update-std-renames` option:

```bash
$ whl2conda --update-std-renames pypi-conda-renames.json
```

## Manual rules

The implicit standard renaming support takes care of most renaming
issues for publicly available packages, but may not work for packages
that come from alternative channels, which may be private to your
organization.

If you encounter these, you can add command line options to with
`whl2conda convert` to rename packages and also to add or drop
packages. You may also rename the package you are building.

### Adding extra packages

You can add one or more extra package dependencies using the `-A` / `--add-depencency`
option. This can be a conda package name and version spec, e.g.:

```bash
$ whl2conda convert -A 'extra-package >=1.2.3' ...
```

You can use this to add dependencies for conda packages that perhaps
do not exist on pypi.

### Dropping a package

Likewise, you can drop packages using `-D` / `--drop-dependency` with
just the package name:

```bash
$ whl2conda convert -D 'some-pypi-only-package'
```

This option also allows you to use [python regular expressions][python-re] to
drop any package that matches a pattern:

```bash
$ whl2conda convert -D 'acme-.*'
```

### <a name="manual-rename">Renaming dependencies</a>

To rename dependencies, use `-R` / `--dependency-rename` with two
arguments, the pypi name followed by the conda name. 
You can also use regular expressions with capture groups, where
`$<n>` will be replaced with the nth capture and `${name}` will
be replaced with the named capture group with given name.

=== "plain"

    ```bash
    $ whl2conda convert -R acme-widgets acme.widgets
    ```

=== "regular expression"

    ```
    $ whl2conda convert -R 'acme-(.*)' 'acme.$1'
    ```

=== "named regular expression"

    ```
    $ whl2conda convert -R 'acme-(?P<part>.*)' 'acme.${part}'
    ```

### Renaming converted package

By default, the name of the generated conda package will be taken
from the project name in the `pyproject.toml` if there is one,
otherwise from the name in the wheel. This can be overriden
using the `--name` command line option:

```bash
$ whl2conda convert acme-widgets-1.2.3-py3-None-any.whl --name acme-pywidgets
```

## Specifying rules in pyproject.toml file

If you are using a `pyproject.toml` file for your project, you can
instead specify how dependencies are modified in the tool options.
This is described in the [next section](pyproject.md).

## <a name="hide-pip">Hiding pip dependencies in dist-info directory for conda</a>

The standard method of building python conda package involves
running `pip install` or the equivalent, which results in a
the package's original pip dependencies and other metadata
being saved to the `METADATA` file in the package's `.dist-info`
directory in `site-packages/` for the environment in which it
is installed. However, in a conda environment, these dependencies
may seem to be incompatible with what is actually installed by conda.
This can sometimes cause serious problems if pip or other standard 
python packaging tools attempt to check or update these dependencies.

Since the actual dependencies for packages installed by conda
are described by the conda package's metadata, and not the metadata
saved in the `.dist-info`, *whl2conda* by default will turn all
regular dependencies in the dist-info into extra dependencies using 
the name `original`. So if you look at the `METADATA` file in the 
dist-info of the generated conda package, you will see entries like:

```email
Requires-Dist: some-package >=1.2; extra == 'original'
```

If you want to leave these dependencies unchanged you can use the
`--keep-pip-dependencies` option to `whl2conda convert`. This is 
not recommended unless you know that you need them.

[anaconda.org]: https://anaconda.org/
[conda]: https://docs.conda.io/projects/conda/en/latest/index.html
[conda-forge]: https://conda-forge.org
[pip-install]: https://pip.pypa.io/en/stable/cli/pip_install/
[pypi.org]: https://pypi.org
[python-re]: https://docs.python.org/3/library/re.html
