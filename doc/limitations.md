*whl2conda* currently only supports conversion ofgeneric pure python wheels
into noarch python conda packages.

It has the following limitations, some of which might be addressed in future
releases.

## Cannot convert from sdist

Currently, only conversion from wheels is supported. Python sdist
distributions are not currently supported. This could possibly be supported in the future.

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
that are declared with the `extra == jupyter` marker. This will be addressed
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


