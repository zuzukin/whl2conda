#  Copyright 2024 Christopher Barber
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
Utilities for working with wheel files
"""

import logging
from pathlib import Path
from typing import Optional, Union
from wheel.wheelfile import WheelFile

__all__ = ["unpack_wheel"]


def unpack_wheel(
    wheel: Union[Path, str],
    dest_dir: Union[Path, str],
    *,
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    Unpack wheel into specified directory.

    Args:
        wheel: location of wheel file to unpack
        dest_dir: destination directory.
    """
    wheel_path = Path(wheel)
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    logger = logger or logging.getLogger(__name__)

    with WheelFile(wheel_path) as wf:
        for zipinfo in wf.filelist:
            extracted = Path(wf.extract(zipinfo, dest_path))
            # copy file permissions (see https://github.com/python/cpython/issues/59999)
            # has no effect on Windows
            extracted.chmod(zipinfo.external_attr >> 16 & 0o777)
            logger.debug("Extracted %s", extracted.relative_to(dest_path))
