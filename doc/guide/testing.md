## Installing into a test environment

You will probably want to test your generated conda package before deploying
it. Currently, `conda install` only supports installing conda package files
without their dependencies, so `whl2conda` provides an `install` subcommand
to install a package into a test environment along with its dependencies:

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

## Installing into conda-bld

Once you are done testing, you may either upload your package to a
conda channel using the approriate tool (e.g. `anaconda upload` or
`curl`). Or you may want to install into your local conda-bld
directory to support `conda install --use-local`. You can do
this using:

```bash
$ whl2conda install mypackage-1.2.3-py_0.conda --conda-bld
```

## Comparing packages

You may wish to compare generated packages against those generated
by conda-build in order both to understand what this tool is doing
and to verify that nothing important is missing. You can do this
using the `whl2conda diff` command with your favorite directory
diff tool. This will unpack the packages into temporary directories,
normalize the metadata files to minimize mismatches and run the
specified diff tool with the given arguments.

For instance,

```bash
$ whl2conda diff \
   dist/mypackage-1.2.3-py_0.conda \
   ~/miniforge3/conda-bld/noarch/mypackage-1.2.3-py_90.tar.bz2 \
   kdiff3
```

Note that some differences are expected in the `info/` directory,
specifically:

* packages generated with whl2conda will not have copy of the recipe
   or test directory
* the about.json file may differ
* the timestamp will be different in the `index.json` file
* the `paths.json` file should reflect any files that differ

There are also expected to be changes in the `site-packages/*dist-info/`
for the package:

* the `INSTALLER` file will contain `whl2conda` instead of `conda`
* the `Requires-Dist` entries in `METADATA` will be modified to add
    `; extra = 'original'`

