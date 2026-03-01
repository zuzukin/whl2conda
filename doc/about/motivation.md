# Motivation

## The Problem

My team relied on conda for managing Python environments and distributing
packages across our organization. While conda excelled at dependency management,
we encountered a significant bottleneck: building conda packages was painfully
slow.

For large projects with multiple interdependent packages, builds could take
30 minutes or more. Most of this time wasn't spent on actual compilation—our
pure-Python packages required no building at all. Instead, conda-build spent the
bulk of its time setting up isolated conda environments just to run
`pip install` and copy files.

## The Insight

This inefficiency led me to examine what conda-build actually does for
pure-Python packages. I discovered that it simply installs the wheel into a
temporary environment and packages the result. All the necessary metadata—
dependencies, entry points, version information—was already present in the wheel
files we were building for our internal PyPI server.

A key question emerged: **What if we could generate conda packages directly
from wheels, bypassing conda-build entirely?**

After studying the specifications for both wheel and conda package formats, I
realized this was not only feasible but relatively straightforward. The main
technical challenge was dependency translation: PyPI and conda-forge use
different package names, so dependencies needed to be renamed during conversion.

## The Solution

I built whl2conda to convert wheels directly into conda packages, extracting
all necessary metadata from the wheel itself. This eliminates two major pain
points:

1. **No conda recipe files needed.** With traditional conda-build, you must
   write and maintain `meta.yaml` recipe files that duplicate information
   already present in your Python package. whl2conda extracts everything it
   needs from the wheel—dependencies, entry points, version information—so
   there's no separate recipe to write or keep in sync.

2. **Automatic dependency translation.** PyPI and conda-forge use different
   package names, so dependencies must be renamed during conversion. We had
   previously solved this using hand-maintained YAML files, but I discovered
   that conda-forge itself maintains a comprehensive mapping database. By
   leveraging this resource, whl2conda handles dependency renaming
   automatically for thousands of packages.

The result is a lightweight tool that converts pure-Python wheels to conda
packages in seconds. No conda environments are needed for conversion,
eliminating the primary bottleneck. The tool's own dependencies are minimal,
and you only need to create a conda environment when testing the resulting
packages.

## Additional Benefits

Beyond building our own packages, we discovered another valuable use case:
converting existing PyPI packages into conda packages for our internal
repositories. While pip packages can be installed into conda environments
easily, conda packages cannot express dependencies on PyPI-only packages. This
creates a gap when you need reliable, reproducible conda environments.

Converting PyPI packages to conda format solved this problem. We could create
conda versions of useful libraries—especially those no longer actively
maintained or whose maintainers had no interest in conda-forge distribution—and
host them in our internal channels. This gave us full control over our
dependency stack while maintaining conda's environment management benefits.

## Broader Applications

whl2conda began as an open-source hobby project to solve my team's specific
pain points. We've successfully used it to eliminate conda-build from our
packaging workflows, dramatically reducing build and deployment times.

The tool may benefit anyone who needs to build conda packages for enterprise
repositories or private channels. It could also benefit conda-forge itself:
converting existing wheels would be far cheaper than rebuilding packages from
source, potentially reducing infrastructure costs for the community.

*—Christopher Barber, creator of whl2conda*

