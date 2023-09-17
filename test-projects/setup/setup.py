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

import os
from setuptools import setup

setup(
    name = "mypkg",
    version = "1.3.4",
    description = "Test package using setup.py",
    author = "John Doe",
    author_email="jdoe@nowhere.com",
    classifiers = [
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    keywords=["python","test"],
    maintainer = "Zuzu",
    maintainer_email= "zuzu@nowhere.com",
    license_files=[
        "LICENSE.md",
        os.path.abspath("LICENSE2.rst"),
    ],
    install_requires = [
        "tables",
        "wheel",
    ],
    extras_require = {
        'bdev': [ 'black' ]
    },
    packages=["mypkg"]
)