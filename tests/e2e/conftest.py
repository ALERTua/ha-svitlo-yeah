"""Mark every test in this folder as e2e, so that the default run deselects it."""

from pathlib import Path

import pytest

E2E_DIR = Path(__file__).parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add the e2e marker before the ``-m`` option deselects items."""
    for item in items:
        if item.path.is_relative_to(E2E_DIR):
            item.add_marker(pytest.mark.e2e)
