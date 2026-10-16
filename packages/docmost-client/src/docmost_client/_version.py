from importlib.metadata import version

__version__ = version("docmost-client")
USER_AGENT = f"docmost-client/{__version__} (unofficial)"
