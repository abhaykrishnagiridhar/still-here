"""The installed package must contain every module the server needs.

pyproject.toml lists the laptop modules by hand. A module that is missing from the list works when run
from this folder, but is absent after a normal `pip install .`, so the server fails to start there.
"""

import tomllib
from pathlib import Path

LAPTOP = Path(__file__).resolve().parent


def listed_modules() -> set[str]:
    data = tomllib.loads((LAPTOP / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["tool"]["setuptools"]["py-modules"])


def real_modules() -> set[str]:
    return {path.stem for path in LAPTOP.glob("*.py") if not path.name.startswith("test_")}


def test_every_laptop_module_is_listed_for_installation():
    assert real_modules() - listed_modules() == set()


def test_no_listed_module_is_missing_from_the_folder():
    assert listed_modules() - real_modules() == set()
