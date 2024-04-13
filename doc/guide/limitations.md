*whl2conda* supports the conversion of generic pure python wheels
into noarch python conda packages.

It has the following limitations and known issues, some of which 
will be addressed in future releases.

## Arbitrary equality clause in version specifiers don't have a conda equivalent

The *arbitrary equality* clause `===` is not supported by conda
and there is no equivalent. This clause is also heavily discouraged 
in dependencies and probably will not occur that often in practice.

We handle this by simplying changinge `===` to `==` but
since this will often not work we also issue a warning.

## File permissions are not copied when run on Windows

Executable file permissions are copied from the wheel when conversion
is run on MacOS or Linux but not Windows. When converting packages that
contain scripts with execute permissions (intended for use on Linux/MacOS),
make sure to avoid Windows when doing the conversion
(see issue [issue 135](https://github.com/zuzukin/whl2conda/issues/135))

## Cannot convert from sdist

Conversion from python sdist distributions is not currently supported. 
This could possibly be supported in the future (see [issue 78](https://github.com/zuzukin/whl2conda/issues/78)).

## Cannot convert from eggs

[Python egg files](https://packaging.python.org/en/latest/discussions/wheel-vs-egg/) 
are also not supported. Since this file format is deprecated and 
[uploads to pypi are no longer allowed](https://blog.pypi.org/posts/2023-06-26-deprecate-egg-uploads/),
we have no plans to support this format.

## Cannot handle dependencies using extras

Currently, for any dependencies that declare extras, the extras dependencies
are not included. For instance, the dependency:

```
black[jupyter]
```

will include the `black` dependency itself, but not any extra dependencies
that are declared with the `extra == 'jupyter'` marker. This will be addressed
in a future release. See [issue 36](https://github.com/zuzukin/whl2conda/issues/36).

## Only supports noarch python

Currently, only generic python conda packages with `noarch: python` will be generated.

In the future we might be able to allow `noarch: python` packages with a pinned python
version (see [issue 50](https://github.com/zuzukin/whl2conda/issues/50)) and
architecture-specific python packages that do not have a pinned python version
(see [issue 51](https://github.com/zuzukin/whl2conda/issues/51)).

## Cannot handle dependencies with environment markers

Currently, dependencies with environment markers are not included in the conda
package. Instead, they could conditionally be included in an OS-specific package
(as mentioned above).

## Pure python only

**whl2conda** does not support wheels with binary content. 


