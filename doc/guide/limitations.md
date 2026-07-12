*whl2conda* supports the conversion of generic python wheels
into conda packages.

It has the following limitations and known issues, some of which 
will be addressed in future releases.

## Arbitrary equality clause in version specifiers has no conda equivalent

The *arbitrary equality* clause `===` is not supported by conda
and there is no equivalent. This clause is also heavily discouraged 
in dependencies and probably will not occur that often in practice.

We handle this by simply changing `===` to `==` but
since this will often not work we also issue a warning.

## File permissions are not copied when run on Windows

Executable file permissions are copied from the wheel when conversion
is run on MacOS or Linux but not Windows. When converting packages that
contain scripts with execute permissions (intended for use on Linux/MacOS),
make sure to avoid Windows when doing the conversion
(see [issue 135](https://github.com/zuzukin/whl2conda/issues/135))

## Cannot convert from sdist

Conversion from python sdist distributions is not currently supported. 
This could possibly be supported in the future (see [issue 78](https://github.com/zuzukin/whl2conda/issues/78)).

## Cannot convert from eggs

[Python egg files](https://packaging.python.org/en/latest/discussions/package-formats/) 
are also not supported. Since this file format is deprecated and 
[uploads to pypi are no longer allowed](https://blog.pypi.org/posts/2023-06-26-deprecate-egg-uploads/),
we have no plans to support this format.

## Dependency extras require options or rules

Conda packages cannot express pip *extras*, so by default the extras
of a dependency like `black[jupyter]` are dropped with a warning and
only the base package dependency is kept. Extras can be handled using
dependency rename rules, the built-in table of known conda packages
(`--known-extras`), or resolution from pypi metadata
(`--resolve-extras`); see
[Dependencies with extras](renaming.md#extras) for details.

## Only supports noarch python by default

By default, only generic python conda packages with `noarch: python` will be generated.

Binary wheels can be converted using the `--allow-impure` flag. See the
[Binary Conversion](binary-conversion.md) guide for details and limitations.

## Dependencies with environment markers

For noarch conversions, dependencies with environment markers are not included
in the conda package. For binary conversions, markers are evaluated against
the target platform and matching dependencies are included. See the
[Binary Conversion](binary-conversion.md) guide for details. 


