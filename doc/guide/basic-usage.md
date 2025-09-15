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
want a wheel, not an sdist (for that see below), so use:

```bash
$ pip download --only-binary :all: --no-deps <some-package-spec>
```

Then you can convert the downloaded wheel using `whl2conda convert`.

Or you can use either the `--from-pypi` or `--from-index` options to `whl2conda convert`
to do this download for you, for example:

```bash
$ whl2conda convert --from-pypi 'some-package ==1.2.3'
```

The `--from-index` option expects either the full URL of the pypi index to
download from or an alias, which may either be taken from a repository entry
in your [~/.pypirc][pypirc] file or from an entry in the users persistent
whl2conda configuration. For instance, you could register a new index using
a command like:

```bash
$ whl2conda config --set pypi-index.myindex https://myindex.com/pypi/
```
and then convert using:

```bash
$ whl2conda convert --from-index myindex 'some-package'
```

## Converting sdist tarballs

*New in version 25.9.0*

You can also convert a source distribution tarball (sdist) to a conda package.
This will only work for distributions that use either a `pyproject.toml` file or a
`setup.py` file to specify their build system and that can be built using `pip wheel`.
Non-pure python packages (i.e. those with compiled extensions) are not supported.

You can download an sdist from pypi using [pip download][pip-download] with the
similar command to the one used for wheels, but specify `--no-binary` instead of

```bash
$ pip download --no-binary :all: --no-deps <some-package-spec>
```

The `convert` subcommand will expand the sdist into a temporary directory and
will build it using `pip wheel` before converting the resulting wheel to a conda package.
This will work for most pure python packages, but could fail if there is something
special about the build process that `pip wheel` cannot handle.

You can also use the `--sdist-from-pypi` and `--sdist-from-index` options to download,
build and convert in one step, e.g.:

```bash
$ whl2conda convert --sdist-from-pypi 'some-package ==1.2.3'
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

You can change the default output format through a persistent user setting, .e.g:

```bash
$ whl2conda config --set conda-format V1
```

You can also specify the format `tree` to generate the conda package
as a directory tree, so that you can examine its contents for
debugging purposes.

[pip-download]: https://pip.pypa.io/en/stable/cli/pip_download/
[pip-wheel]: https://pip.pypa.io/en/stable/cli/pip_wheel/
[pypi]: https://pypi.org
[pypirc]: https://packaging.python.org/en/latest/specifications/pypirc/


