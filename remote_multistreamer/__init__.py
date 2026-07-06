"""Remote Multi-Streamer package."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = ["__version__"]


def _read_version() -> str:
    try:
        return version("remote-multistreamer")
    except PackageNotFoundError:
        pass

    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)["project"]["version"]


__version__ = _read_version()
