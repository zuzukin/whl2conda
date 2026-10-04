# Building from Recipes

The `whl2conda build` command is a limited drop-in replacement for
`conda build` (and, for v1 recipes, `rattler-build build`) that builds
a conda package from an existing recipe without creating any build
environments. It is primarily intended to make it easy to evaluate
whl2conda against a project's existing recipe: run both tools on the
same recipe and compare the resulting packages.

Instead of solving and creating build/host/test environments, whl2conda:

1. renders the recipe (using conda-build or rattler-build),
2. runs the recipe's `pip install .` build script as a
   [pip wheel][pip-wheel] build in the current environment,
3. converts the resulting wheel directly into a conda package, and
4. runs the recipe's tests against the package in a fresh conda
   environment.

The package is named by the recipe, and its dependencies are those of
the wheel together with the recipe's run requirements, which take
precedence over the wheel's dependencies on the same packages. The
python dependency of a binary package always comes from the wheel,
since it depends on how the wheel was built. The recipe's run
constraints (`run_constrained`, or `run_constraints` in v1 recipes)
become the run constraints of the package.

Because there is no build environment, this is much faster than
`conda build`, but it only works for recipes that:

* have a build script consisting of a single `pip install .` or
  `pip wheel .` command (extra pip options before or after the
  project directory are fine), and
* produce a single output package.

Both pure python (`noarch: python`) and platform-specific binary
recipes are supported. For binary recipes, the wheel is built with
your local toolchain via the project's build backend — not in the
recipe's `build`/`host` conda environments — so this works for
self-contained extension modules but not for recipes that require
conda-provided compilers or libraries (see the
[Binary Conversion](binary-conversion.md) guide for the conversion
limitations), and the built wheel reflects your local toolchain
settings (e.g. the macOS deployment target). On Linux, the locally
built wheel is not a portable manylinux wheel, so the package is given
a `__glibc` dependency requiring at least the glibc version of the
build machine.

Recipes that use variant-dependent expressions such as
`${{ compiler('c') }}` or `${{ stdlib('c') }}` need a variant
configuration file to render. Variant files in the recipe directory
(`conda_build_config.yaml`, and for v1 recipes also `variants.yaml`)
are loaded automatically, and others can be supplied with
`-m`/`--variant-config-files`. When the recipe renders to a variant
for each of several python versions, only the variant for the python
version used in the build - the one running whl2conda - is produced.

The `--output`, `-t`/`--test`, and `--skip-existing` options remain
restricted to noarch recipes, since a binary package's file name
cannot be predicted before the wheel is built.

### Validation against conda-forge

The whl2conda test suite includes a real-world suite that builds a
sample of conda-forge feedstock recipes for binary packages with
`whl2conda build`, using the local toolchain, and semantically compares
each result against the real conda-forge package of the same version
using `whl2conda diff`. It is not part of the regular tests and only
runs on demand:

```bash
pixi run build-compare
```

This requires network access and a C/C++ compiler, and writes a summary
report to `build-compare-report.md` / `build-compare-report.json`.

## Supported recipe formats

Both recipe formats are supported. The format is detected from the
file in the recipe directory:

* **`meta.yaml`** — classic conda-build recipes. Rendering requires
  [conda-build], which is used in-process when it is installed in the
  current environment and is otherwise run in the conda `base`
  environment.

* **`recipe.yaml`** — v1 recipes ([CEP 13]/[CEP 14]), as built by
  [rattler-build]. Rendering requires either the [py-rattler-build]
  python package or the `rattler-build` command on the PATH.
  v1 recipes must declare `noarch: python`.

## Basic usage

```bash
$ whl2conda build path/to/recipe/
```

By default this builds the package, runs the recipe's tests in a fresh
conda environment, and installs the result into your local conda-bld
directory (like `conda build`). Some useful options:

```bash
# write the package to a directory instead of conda-bld
$ whl2conda build recipe/ --output-folder dist/

# check whether whl2conda can build a recipe, without building
$ whl2conda build recipe/ --check

# print the output package path without building
$ whl2conda build recipe/ --output

# test the previously built package
$ whl2conda build recipe/ -t

# build without testing / without installing
$ whl2conda build recipe/ --no-test
$ whl2conda build recipe/ -b
```

Run `whl2conda build --help` or see the
[command reference](../reference/cli/whl2conda-build.md) for the full
option list.

## conda build option compatibility

`whl2conda build` accepts most `conda build` options so that it can be
dropped into existing scripts:

* Options that map onto whl2conda's build model are honored:
  `-c`/`--channel`, `--output-folder`, `--package-format`, `--croot`,
  `--python`, `--skip-existing`, `-q`/`--quiet`, `--debug`, `-t`,
  `-b`/`--build-only`, `--no-test`, and `--output`.

* Options that do not apply to this build model (e.g.
  `--variant-config-files`, `--numpy`, `--dirty`) are accepted and
  ignored with a warning.

* Options whose omission would silently change the meaning of a build
  pipeline — package uploading/signing options and non-python language
  support (`--perl`, `--R`, `--lua`) — are rejected with an error.

There are also a few whl2conda extensions: `--check` (validate the
recipe without building), `--extra-deps` (additional conda
dependencies), `--keep-test-env` (keep the test environment for
debugging), and `--build-isolation`.

Recipes usually pass `--no-build-isolation` to pip, because the
project's build requirements are installed in the recipe's host
environment. Since whl2conda does not create that environment, the
build requirements must instead be installed in the environment that
`whl2conda build` is run from. Alternatively, the `--build-isolation`
option removes `--no-build-isolation` from the pip command, so that pip
downloads and installs the build requirements declared by the project
into an isolated build environment.

## Evaluating whl2conda against your recipe

To assess whether whl2conda produces an acceptable package for your
project, build the same recipe with both tools and compare the results
with [whl2conda diff](testing.md):

```bash
$ conda build my-recipe/ --output-folder conda-build-out/
$ whl2conda build my-recipe/ --output-folder whl2conda-out/
$ whl2conda diff conda-build-out/noarch/mypkg-1.2.3-py_0.conda \
    whl2conda-out/noarch/mypkg-1.2.3-py_0.conda
```

The diff analysis reports notable and unexpected differences while
suppressing differences that are expected between whl2conda-generated
and recipe-built packages.

## Package tests

The recipe's test section is run against the generated package in a
fresh conda environment created with `whl2conda install`:

* For `meta.yaml` recipes, the `test:` section's `requires`,
  `imports`, `commands`, and `source_files` entries are honored.

* For `recipe.yaml` recipes, the `tests:` list's `python` elements
  (`imports`, `pip_check`) and `script` elements (with
  `requirements.run` and `files.source`) are honored;
  `package_contents` and `downstream` elements are ignored with a
  warning. Note that whl2conda runs all test elements in a single
  test environment, unlike rattler-build, which creates a separate
  environment per element.

[conda-build]: https://docs.conda.io/projects/conda-build/
[rattler-build]: https://rattler.build/
[py-rattler-build]: https://pypi.org/project/py-rattler-build/
[CEP 13]: https://github.com/conda/ceps/blob/main/cep-0013.md
[CEP 14]: https://github.com/conda/ceps/blob/main/cep-0014.md
[pip-wheel]: https://pip.pypa.io/en/stable/cli/pip_wheel/
