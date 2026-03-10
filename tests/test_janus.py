"""Basic tests for the janus package."""

import janus


def test_version():
    """Ensure the package exposes a version string."""
    assert isinstance(janus.__version__, str)
    assert len(janus.__version__) > 0


def test_all_exported():
    """Ensure __all__ is defined and contains expected symbols."""
    assert isinstance(janus.__all__, list)
    assert "Client" in janus.__all__
    assert "Session" in janus.__all__
    assert "Node" in janus.__all__
