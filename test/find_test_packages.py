#  Copyright 2023 Christopher Barber
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""
Script to find candidate test packages that use pypi/conda renamed packages.
"""

import json
from pathlib import Path
import urllib.request
from typing import Any

from whl2conda.api.stdrename import load_std_renames

REPODATA_URL = "https://conda.anaconda.org/conda-forge/noarch/repodata.json"


def main():
    """Main routine"""
    print(f"downloading {REPODATA_URL}")
    with urllib.request.urlopen(REPODATA_URL) as response:
        content = response.read()

    repodata = json.loads(content, encoding="utf8")

    print("update stdrenames")

    # standard pypi -> conda mappings
    stdrenames = load_std_renames(update=True)
    # make a set of the conda names
    conda_renames = set(stdrenames.values())

    candidates: dict[str, Any] = {}

    print("filtering")
    for _k, v in repodata.get("packages.conda", {}).items():
        if v.get("noarch") != "python":
            continue
        depends = set(v.get("depends", ()))
        depends &= conda_renames
        if not depends:
            continue
        name = v.get("name")
        v["conda-renames"] = list(depends)
        v["n-renames"] = len(depends)
        prev = candidates.get(name)
        if not prev or prev.get("timestamp", 0) < v.get("timestamp", 0):
            candidates[name] = v

    sorted_candidates = sorted(
        candidates.values(),
        key=lambda v: v.get("n-renames", 0),
        reverse=True,
    )

    candidate_file = Path("packages-with-renamed-dependencies.json")
    print(f"writing {candidate_file}")
    candidate_file.write_text(json.dumps(sorted_candidates, indent=2))


if __name__ == "__main__":
    main()
