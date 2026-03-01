# Motivation

## Why whl2conda Exists

Many teams, including mine, rely on conda for managing Python environments and
for distributing packages. However, we found the process of building and
releasing conda packages to be slow and cumbersome—especially for large projects
with multiple interdependent packages. Some builds could take 30 minutes or
more, with much of that time spent by conda-build just setting up environments.

For our pure-Python packages, the actual package construction was trivial:
conda-build simply ran `pip install` in a prepared environment. All the
necessary metadata was already present in the wheel files we built for our
internal PyPI server. This led to a key question: **What if we could generate a
conda package directly from a pip wheel?**

After examining the specifications and structure of both wheels and conda
packages, I realized that direct conversion was conceptually straightforward.
The main challenge was renaming dependencies from PyPI to their conda-forge
equivalents. Previously, we managed this with custom YAML files, but I
discovered that conda-forge maintains a comprehensive database of PyPI-to-conda
mappings, which could be leveraged for automation.

With this insight, I developed whl2conda—a tool that quickly converts
pure-Python wheels into conda packages, bypassing the need for conda-build.
Building packages now takes only seconds, with most time spent packing and
unpacking zip files. No conda environments are required for conversion, and the
tool itself has minimal dependencies. You only need to build a conda environment
if you want to test the resulting package.

whl2conda began as an open-source hobby project for internal use, but it may
benefit anyone needing to build conda packages for enterprise or private
channels. It could also offer a more efficient way to build conda-forge
feedstocks, potentially reducing costs associated with conda-forge builds.
