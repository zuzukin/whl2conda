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
