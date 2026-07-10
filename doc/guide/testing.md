## Installing into a test environment

You will probably want to test your generated conda packages before deploying
them. Currently, `conda install` only supports installing conda package files
without their dependencies, so `whl2conda` provides an `install` subcommand
to install one or more package files into a test environment along with their dependencies:

```bash
$ whl2conda install mypackage-1.2.3-py_0.conda -n test-env
```

If you want to create an environment in a temporary directory:

```bash
$ whl2conda install mypackage-1.2.3-py_0.conda --create -p tmp-dir
```

You can also add additional dependencies or other options to pass
to the underlying `conda install` command:

```bash
$ whl2conda install mypackage-1.2.3-py_0.conda \
   --create -p tmp-dir \
   --extra pytest -c my-channel
```

If you are building multiple packages with an interdependency you should install
them in a single install command, e.g.:

```bash
$ whl2conda install mypackage-1.2.3-py_0.conda mycorepackage-1.2.3-py_0.conda ...
```

## Installing into conda-bld

Once you are done testing, you may upload your package to a
conda channel using the appropriate tool (e.g. `anaconda upload` or
`curl`), or you may install into your local conda-bld
directory to support `conda install --use-local`. You can do
this using:

```bash
$ whl2conda install mypackage-1.2.3-py_0.conda --conda-bld
```

## Comparing packages

You may wish to compare generated packages against those generated
by conda-build or rattler-build (e.g. from conda-forge) in order both
to understand what this tool is doing and to verify that nothing
important is missing. You can do this with the `whl2conda diff`
command:

```bash
$ whl2conda diff \
   dist/mypackage-1.2.3-py_0.conda \
   ~/miniforge3/conda-bld/noarch/mypackage-1.2.3-py_0.tar.bz2
```

By default, this semantically analyzes the differences between the two
packages and prints a report of notable and unexpected differences —
missing dependencies, missing or altered files, unrenamed pip
dependencies, mismatched entry points, and so on — while suppressing
differences that are *expected* when comparing a whl2conda-generated
package against a recipe-built one, such as differing build strings and
timestamps, run-export dependencies added by compilers, regenerated
entry point scripts, differing binary module contents, and dist-info
bookkeeping details. The command exits with a non-zero status if any
unexpected differences are found, so it can be used in scripts and CI.

Useful options (see the
[command reference](../reference/cli/whl2conda-diff.md) for the full list):

* `--all` also shows the expected differences
* `--strict` treats notable differences as errors
* `--ignore <category>` suppresses a category of differences
* `--run-export <name>` treats additional dependency names as benign
  run-exports when only present in the reference package
* `--json` emits the analysis as JSON

Alternatively, you can inspect the raw differences with your favorite
directory diff tool using the `-T` option. This will unpack the
packages into temporary directories, normalize the metadata files to
minimize mismatches and run the specified diff tool with the given
arguments:

```bash
$ whl2conda diff \
   dist/mypackage-1.2.3-py_0.conda \
   ~/miniforge3/conda-bld/noarch/mypackage-1.2.3-py_0.tar.bz2 \
   -T kdiff3
```

