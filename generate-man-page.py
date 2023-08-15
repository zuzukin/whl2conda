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
Generate a markdown man page from the command line help
"""

from __future__ import annotations

import argparse
import subprocess

def main():
    parser = argparse.ArgumentParser(

    )

    parser.add_argument(
        "--out", metavar="<output-file>",
    )

    help = subprocess.check_output(
        ["whl2conda", "--help"]
    )



if __name__ == "__main":
    main()
