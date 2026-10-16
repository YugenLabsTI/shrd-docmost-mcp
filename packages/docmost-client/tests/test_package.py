import docmost_client


def test_exposes_installed_version() -> None:
    assert docmost_client.__version__ == "0.1.0"
