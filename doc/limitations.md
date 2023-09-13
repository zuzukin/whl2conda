*whl2conda* currently only supports conversion of generic pure python wheels
into noarch python conda packages.

It has the following limitations, some of which will be addressed in future
releases.

## Version specifiers are not translated

Version specifiers in dependencies are simply copied from
the wheel without modification. This works for many cases,
but since the version comparison operators for pip and conda
are slightly different, some version specifiers will not work
properly in conda. Specifically,

* the *compatible release* operator `~=` is not supported by conda.
    To translate, use a double expression with `>=` and `*`, e.g.:
    `~= 1.2.3` would become `>=1.2.3,1.2.*` in conda. This form is
    also supported by pip, so this is a viable workaround for packages
    you control.
  
  
* the *arbitrary equality* clause `===` is not supported by conda.
    I do not believe there is an equivalent to this in conda, but
    this clause is also heavily discouraged in dependencies and
    might not even match the corresponding conda package.

(*There are other operations supported by conda but not pip, but
the are not a concern when translating from pip specifiers.*)

As a workaround, users can switch to compatible specifier syntax when
possible and otherwise can remove the offending package and add it
back with compatible specifier syntax, e.g.:

```bash
whl2conda mywheel-1.2.3-py3-none-any.whl -D foo -A 'foo >=1.2.3,1.2.*'
```

This will be fixed in a future release 
(see [issue 84](https://github.com/zuzukin/whl2conda/issues/84)).

## Cannot convert from sdist

Currently, only conversion from wheels is supported. Conversion from python sdist
distributions are not currently supported. This could possibly be supported in 
the future (see [issue 78](https://github.com/zuzukin/whl2conda/issues/78)).

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


