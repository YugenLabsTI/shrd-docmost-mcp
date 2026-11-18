import tomllib
from pathlib import Path

from packaging.requirements import Requirement

import docmost_client
import yugen_docmost_mcp

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _client_requirement() -> Requirement:
    dependencies = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    return next(r for r in map(Requirement, dependencies) if r.name == "docmost-client")


def test_exposes_installed_version() -> None:
    # Compared with pyproject.toml, not a literal: release-please bumps the version there.
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    assert yugen_docmost_mcp.__version__ == declared


def test_requires_a_docmost_client_that_supports_docmost_0_97_0() -> None:
    # docmost-client 0.1.1 refuses Docmost 0.97.0; upgrading only the server must not keep it.
    allowed = _client_requirement().specifier

    assert "0.1.1" not in allowed
    assert "0.1.2" in allowed
    assert docmost_client.__version__ in allowed
