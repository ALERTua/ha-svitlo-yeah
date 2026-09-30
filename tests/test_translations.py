"""Tests for the translation files."""

import json
from pathlib import Path

import pytest

from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS

TRANSLATIONS = Path(__file__).parent.parent / (
    "custom_components/svitlo_yeah/translations"
)
LANGUAGES = ["en", "uk"]


def _load(language: str) -> dict:
    """Load the translation file of a language."""
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


def _keys(node: dict, prefix: str = "") -> set[str]:
    """Return the dotted paths of all texts in a translation tree."""
    output = set()
    for key, value in node.items():
        if isinstance(value, dict):
            output |= _keys(value, f"{prefix}{key}.")
        else:
            output.add(f"{prefix}{key}")
    return output


def test_languages_have_the_same_keys():
    """Each text exists in each language."""
    en, uk = (_keys(_load(language)) for language in LANGUAGES)
    assert en - uk == set()
    assert uk - en == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_dtek_provider_has_a_name(language):
    """Each DTEK provider has a name, which device names and repair issues use."""
    common = _load(language)["common"]
    assert {p for p in DTEK_PROVIDER_URLS if not common.get(p)} == set()
