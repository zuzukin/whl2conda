## Converting an existing wheel

To convert an existing Python wheel to a conda package, you only need to 
run `whl2conda convert`:

```bash
$ whl2conda convert mypackage-1.2.3-py3-none-any.whl
Reading mypackage-1.2.3-py3-none-any.whl
Writing mypackage-1.2.3-py_0.conda
```

By default, this will create the conda package in the same directory
as the wheel. You can specify a different output directory using the
`--out-dir`, e.g.:

```bash
$ whl2conda convert mypackage-1.2.3-py3-none-any.whl --out-dir conda-dist
```

This will automatically convert pypi package dependencies to their corresponding
conda package, renaming them as needed. Standard pypi/conda name mappings are
taken from conda-forge. This will do the right thing for most packages, but
you may also need to provide your own dependency rules to modify the dependencies.
This is described in the section on [Dependency Modification](renaming.md)

## Downloading wheels

If you want to create a conda package for a pure python package from [pypi] that doesn't
currently have one available on a public channel, you can download the wheel
using [pip download][pip-download]. You do not need to download dependencies and 
want a wheel, not an sdist, so use:

```bash
$ pip download --only-binary:all: --no-deps <some-package-spec>
```

Then you can convert the downloaded wheel using `whl2conda convert`.

Or you can use either the `--from-pypi` or `--from-index` options to `whl2conda convert`
to do this download for you, for example:

```bash
$ whl2conda convert --from-pypi 'some-package ==1.2.3'
```

## Building from project directories

If you are creating a conda package for your own python project that uses
either a `pyproject.toml` file or a `setup.py` file, you can specify the
project directory instead of a wheel file, or you can omit the positional
argument if the project is located in the current working directory.

```bash
$ whl2conda convert my-project/
```

When run this way, there must be a `pyproject.toml` or `setup.py` file 
in the specified directory. If there isa `pyproject.toml` file, *whl2conda* will
read any project-specific options from the `[tool.whl2conda]` section
(see [Configuring pyproject.toml](pyproject.md) for details) and will
then look for a wheel in the `dist/` subdirectory of the project.

If there is only one `.whl` file in the `dist/` directory, that will
be used. Otherwise, if the there is an interactive terminal and the 
`--batch` option  has not been specified, *whl2conda* will prompt
the user to choose a wheel or to build one using [pip wheel][pip-wheel].

You can use the `--build-wheel` option to force the wheel to be built
without prompting. So you can build both your project's wheel and
a conda package non-interactively using the command:

```bash
$ whl2conda convert my-project/ --build-wheel --batch --yes
```

## Output formats

By default, `whl2conda convert` will generate a V2 format file with
a `.conda` extension.  If you instead want the old V1 format, which
uses the `.tar.bz2` extension, you can use the `--format` option:

```bash
$ whl2conda convert mypackage-1.2.3-py3-none-any.whl --format V1
Reading mypackage-1.2.3-py3-none-any.whl
Writing mypackage-1.2.3-py_0.tar.bz2
```

You can also specify the format `tree` to generate the conda package
as a directory tree, so that you can examine its contents for
debugging purposes.

[pip-download]: https://pip.pypa.io/en/stable/cli/pip_download/
[pip-wheel]: https://pip.pypa.io/en/stable/cli/pip_wheel/
[pypi]: https://pypi.org

