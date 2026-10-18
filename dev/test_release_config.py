"""The release-please configuration and the dependency ranges stay in step with the workspace.

release-please only knows the packages listed in its config, and uv does not check the
version ranges between workspace members, so these tests catch the drift instead.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = sorted(path.parent for path in (ROOT / "packages").glob("*/pyproject.toml"))


def project(package: Path) -> dict[str, Any]:
    return tomllib.loads((package / "pyproject.toml").read_text())["project"]


def release_config() -> dict[str, Any]:
    return json.loads((ROOT / "release-please-config.json").read_text())


def relative(package: Path) -> str:
    return package.relative_to(ROOT).as_posix()


def test_every_workspace_package_is_released() -> None:
    configured = release_config()["packages"]
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())

    assert sorted(configured) == [relative(package) for package in PACKAGES]
    assert sorted(manifest) == sorted(configured)


@pytest.mark.parametrize("package", PACKAGES, ids=lambda package: package.name)
def test_each_package_is_tagged_with_its_name_and_keeps_the_lockfile_in_step(
    package: Path,
) -> None:
    config = release_config()
    entry = config["packages"][relative(package)]
    name = project(package)["name"]

    assert config["release-type"] == "python"
    assert entry["component"] == name
    assert entry["extra-files"] == [
        {
            "type": "toml",
            "path": "/uv.lock",
            "jsonpath": f"$.package[?(@.name.value=='{name}')].version",
        }
    ]
    locked = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    assert [item["version"] for item in locked if item["name"] == name] == [
        project(package)["version"]
    ]


def test_workspace_dependencies_accept_the_current_version() -> None:
    versions = {project(package)["name"]: project(package)["version"] for package in PACKAGES}
    checked = 0
    for package in PACKAGES:
        for raw in project(package).get("dependencies", []):
            requirement = Requirement(raw)
            if requirement.name in versions:
                checked += 1
                assert requirement.specifier.contains(versions[requirement.name]), (
                    f"{project(package)['name']} requires {raw}, but the workspace has "
                    f"{requirement.name} {versions[requirement.name]}: update the range."
                )
    assert checked, "expected yugen-docmost-mcp to depend on docmost-client"
