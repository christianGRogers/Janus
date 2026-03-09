"""Basic tests for the janus package."""

import janus


def test_version():
    """Ensure the package exposes a version string."""
    assert isinstance(janus.__version__, str)
    assert len(janus.__version__) > 0


def test_all_exported():
    """Ensure __all__ is defined and is a list."""
    assert isinstance(janus.__all__, list)
