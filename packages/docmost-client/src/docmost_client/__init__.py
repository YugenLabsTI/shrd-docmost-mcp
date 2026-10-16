"""Unofficial typed client for the internal API of self-hosted Docmost Community Edition."""

from importlib.metadata import version

from docmost_client.errors import ConfigError, DocmostError
from docmost_client.settings import DocmostSettings

__version__ = version("docmost-client")

__all__ = ["ConfigError", "DocmostError", "DocmostSettings", "__version__"]
