import tomllib
from pathlib import Path

import docmost_client

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_exposes_installed_version() -> None:
    # Compared with pyproject.toml, not a literal: release-please bumps the version there.
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    assert docmost_client.__version__ == declared
