import yugen_docmost_mcp


def test_exposes_installed_version() -> None:
    assert yugen_docmost_mcp.__version__ == "0.1.0"
