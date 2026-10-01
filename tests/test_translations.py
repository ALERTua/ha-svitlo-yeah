"""Tests for the translation files."""

import ast
import json
import string
from pathlib import Path

import pytest

from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS

TRANSLATIONS = Path(__file__).parent.parent / (
    "custom_components/svitlo_yeah/translations"
)
CONFIG_FLOW = TRANSLATIONS.parent / "config_flow.py"
LANGUAGES = ["en", "uk"]
# Home Assistant aborts with these reasons: _async_abort_entries_match with
# already_configured, async_update_reload_and_abort of a reauth with
# reauth_successful
HA_ABORT_REASONS = {"already_configured", "reauth_successful"}


def _load(language: str) -> dict:
    """Load the translation file of a language."""
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


def _texts(node: dict, prefix: str = "") -> dict[str, str]:
    """Return all texts of a translation tree by their dotted paths."""
    output = {}
    for key, value in node.items():
        if isinstance(value, dict):
            output |= _texts(value, f"{prefix}{key}.")
        else:
            output[f"{prefix}{key}"] = value
    return output


def _placeholders(text: str) -> set[str]:
    """Return the names of the placeholders in a translation text."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _abort_reasons() -> set[str]:
    """Return each text that config_flow.py passes as an abort reason."""
    tree = ast.parse(CONFIG_FLOW.read_text(encoding="utf-8"))
    return {
        node.value
        for keyword in ast.walk(tree)
        if isinstance(keyword, ast.keyword) and keyword.arg == "reason"
        for node in ast.walk(keyword.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _form_errors() -> set[str]:
    """Return each text that config_flow.py puts into the errors of a form."""
    tree = ast.parse(CONFIG_FLOW.read_text(encoding="utf-8"))
    return {
        node.value
        for assign in ast.walk(tree)
        if isinstance(assign, ast.Assign)
        and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "errors"
            for target in assign.targets
        )
        for node in ast.walk(assign.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _exception_keys() -> set[str]:
    """Return each translation_key that the integration gives to an exception."""
    return {
        keyword.value.value
        for path in TRANSLATIONS.parent.rglob("*.py")
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(call, ast.Call)
        and any(k.arg == "translation_domain" for k in call.keywords)
        for keyword in call.keywords
        if keyword.arg == "translation_key" and isinstance(keyword.value, ast.Constant)
    }


def test_languages_have_the_same_keys():
    """Each text exists in each language."""
    en, uk = (set(_texts(_load(language))) for language in LANGUAGES)
    assert en - uk == set()
    assert uk - en == set()


def test_languages_use_the_same_placeholders():
    """A text has the same placeholders in each language, as the code sends one set."""
    en, uk = (_texts(_load(language)) for language in LANGUAGES)
    assert {
        key
        for key in en.keys() & uk.keys()
        if _placeholders(en[key]) != _placeholders(uk[key])
    } == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_abort_reason_has_a_text(language):
    """Each abort reason has a text, because the dialog shows a bare key without it."""
    reasons = _abort_reasons()
    assert reasons  # the parser found the reasons of config_flow.py

    abort = _load(language)["config"]["abort"]
    assert {r for r in reasons | HA_ABORT_REASONS if not abort.get(r)} == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_form_error_has_a_text(language):
    """Each form error has a text, because the form shows a bare key without it."""
    errors = _form_errors()
    assert errors  # the parser found the errors of config_flow.py

    texts = _load(language)["config"]["error"]
    assert {e for e in errors if not texts.get(e)} == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_exception_has_a_text(language):
    """Each translated exception has a text, because the UI shows a bare key without it."""
    keys = _exception_keys()
    assert keys  # the parser found the exceptions of the integration

    texts = _load(language).get("exceptions", {})
    assert {k for k in keys if not texts.get(k, {}).get("message")} == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_field_has_a_description(language):
    """Each field of a config flow form has a text under it that explains it."""
    steps = _load(language)["config"]["step"]
    assert {
        f"{step_id}.{field}"
        for step_id, step in steps.items()
        for field in step.get("data", {})
        if not step.get("data_description", {}).get(field)
    } == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_dtek_provider_has_a_name(language):
    """Each DTEK provider has a name, which device names and repair issues use."""
    common = _load(language)["common"]
    assert {p for p in DTEK_PROVIDER_URLS if not common.get(p)} == set()
