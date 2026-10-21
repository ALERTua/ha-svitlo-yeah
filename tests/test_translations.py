"""Tests for the translation files."""

import ast
import json
import re
import string
from pathlib import Path

import pytest

from custom_components.svitlo_yeah import const
from custom_components.svitlo_yeah.button import CHECK_GROUP_BUTTON, REFRESH_BUTTON
from custom_components.svitlo_yeah.config_flow import (
    NOT_FOUND_ERRORS,
    SEARCH_AGAIN,
    SEARCH_AGAIN_TEXTS,
)
from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS
from custom_components.svitlo_yeah.sensor import GROUP_SENSOR, SENSORS

TRANSLATIONS = Path(__file__).parent.parent / (
    "custom_components/svitlo_yeah/translations"
)
CONFIG_FLOW = TRANSLATIONS.parent / "config_flow.py"
README = Path(__file__).parent.parent / "README.md"
LANGUAGES = ["en", "uk"]
# The provider options whose source covers one region with its oblast
REGION_OPTIONS = ("dtekjsonprovider_",)
# The letters of the oblenergo abbreviations, as the English region names spell
# them, for example Khmelnytskyi, Chernihiv and Zhytomyr
LATIN = dict(
    zip(
        "ВЕЖЗЛОПРТХЧ",
        ("V", "E", "Zh", "Z", "L", "O", "P", "R", "T", "Kh", "Ch"),
        strict=True,
    )
)
# The flow aborts with this reason through AbortFlow, which the parser of the abort
# reasons does not read
HA_ABORT_REASONS = {"already_configured"}
# The steps of the address flow, and the errors of its form that the code does not
# read from a table (the not found errors come from NOT_FOUND_ERRORS)
ADDRESS_STEPS = ("yasno_method", "address", "pick_city", "pick_street", "house")
ADDRESS_ERRORS = {
    "city_too_short",
    "street_too_short",
    "name_not_unique",
    "street_without_houses",
    "yasno_no_answer",
    "address_group_not_listed",
}


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


def _entry_descriptions() -> set[str]:
    """Return each key that config_flow.py gives as the description of a new entry."""
    tree = ast.parse(CONFIG_FLOW.read_text(encoding="utf-8"))
    return {
        keyword.value.value
        for keyword in ast.walk(tree)
        if isinstance(keyword, ast.keyword)
        and keyword.arg == "description"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }


def _exception_keys() -> set[str]:
    """Return each translation_key that the integration gives to an exception."""
    return {
        keyword.value.value
        for path in TRANSLATIONS.parent.rglob("*.py")
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(call, ast.Call)
        and (
            any(k.arg == "translation_domain" for k in call.keywords)
            # The coordinators stop the setup of a broken entry through it
            or getattr(call.func, "attr", None) == "_required_setting"
        )
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
def test_each_entry_description_has_a_text(language):
    """The dialog of a new entry shows a bare key when its description has no text."""
    keys = _entry_descriptions()
    assert keys  # the parser found the descriptions of config_flow.py

    texts = _load(language)["config"]["create_entry"]
    assert {k for k in keys if not texts.get(k)} == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_exception_has_a_text(language):
    """Each translated exception has a text: without it, the UI shows a bare key."""
    keys = _exception_keys()
    assert keys  # the parser found the exceptions of the integration

    texts = _load(language).get("exceptions", {})
    assert {k for k in keys if not texts.get(k, {}).get("message")} == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_repair_issue_has_a_title_and_a_description(language):
    """Each repair issue of const.py has a title and a description for Repairs."""
    keys = [value for name, value in vars(const).items() if name.startswith("ISSUE_")]
    assert keys  # the issues of const.py

    issues = _load(language).get("issues", {})
    assert [
        key
        for key in keys
        if not all(issues.get(key, {}).get(part) for part in ("title", "description"))
    ] == []


def test_removed_provider_texts_name_the_placeholders_that_the_code_sends():
    """
    The error, the abort and the issue of a removed provider name its placeholders.

    Each one gets the provider and the integration, and the issue gets the entry.
    """
    texts = _load("en")
    sent = {"provider", "integration"}
    assert _placeholders(texts["exceptions"]["provider_removed"]["message"]) == sent
    assert _placeholders(texts["config"]["abort"]["provider_removed"]) == sent
    issue = texts["issues"]["provider_removed"]
    assert _placeholders(issue["title"]) == {"entry"}
    assert _placeholders(issue["description"]) == {"entry", *sent}


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_sensor_and_button_has_a_name(language):
    """Each sensor and button has a name: without it, the entity has no name."""
    entities = _load(language)["entity"]
    descriptions = {
        "sensor": (*SENSORS, GROUP_SENSOR),
        "button": (REFRESH_BUTTON, CHECK_GROUP_BUTTON),
    }

    assert {
        f"{platform}.{d.translation_key}"
        for platform, group in descriptions.items()
        for d in group
        if not entities[platform].get(d.translation_key, {}).get("name")
    } == set()


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
def test_each_translation_key_of_the_code_has_a_text(language):
    """
    Each translation key that const.py names has a text, for example an event name.

    Home Assistant takes the English text for another language, so a name is
    missing only when en.json lacks the key.
    """
    prefix = f"component.{const.DOMAIN}."
    keys = [
        value
        for value in vars(const).values()
        if isinstance(value, str) and value.startswith(prefix)
    ]
    assert keys  # the event names at least

    texts = _texts(_load(language))
    assert [key for key in keys if not texts.get(key.removeprefix(prefix))] == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_dtek_provider_has_a_name(language):
    """Each DTEK provider has a name, which device names and repair issues use."""
    common = _load(language)["common"]
    assert {p for p in DTEK_PROVIDER_URLS if not common.get(p)} == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_provider_option_names_the_region_of_its_devices(language):
    """The provider list names the region as the devices do, for example Kyiv Oblast."""
    texts = _load(language)
    options = texts["selector"]["provider"]["options"]
    regions = {
        key: key.split("_", 1)[1] for key in options if key.startswith(REGION_OPTIONS)
    }
    assert len(regions) == len(DTEK_PROVIDER_URLS)

    assert [
        key
        for key, region in regions.items()
        if texts["common"][region] not in options[key]
    ] == []


def _option_parts(language: str) -> dict[str, list[str]]:
    """Return the parts of each provider option: DTEK, Lviv and Oblast, LOE."""
    options = _load(language)["selector"]["provider"]["options"]
    return {key: text.split(" — ") for key, text in options.items()}


def test_readme_names_each_provider_as_the_provider_list():
    """Each row of the README regions table has the parts of a provider option."""
    rows = re.findall(
        r"^\| \*\*(.+?)\*\* *\| (\S+) *\|",
        README.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    # «DTEK — Kyiv Oblast» has no third part: the provider is the first one
    listed = [
        (parts[1], parts[-1] if len(parts) == 3 else parts[0])
        for parts in _option_parts("en").values()
    ]

    assert sorted(rows) == sorted(listed)


def test_each_ukrainian_abbreviation_spells_the_english_one():
    """An oblenergo has one abbreviation in both lists, for example ЖОЕ and ZhOE."""
    english = _option_parts("en")
    ukrainian = {
        key: parts[-1]
        for key, parts in _option_parts("uk").items()
        if key.startswith(REGION_OPTIONS) and len(parts) == 3
    }
    assert len(ukrainian) == 11  # the options of the oblenergos

    assert {
        key: "".join(LATIN[letter] for letter in abbreviation)
        for key, abbreviation in ukrainian.items()
    } == {key: english[key][-1] for key in ukrainian}


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_error_of_the_address_form_has_a_text(language):
    """
    Each error of the address form has a text, because the form shows a bare key.

    The not found errors come from a table, so the parser of the form errors above
    does not read them.
    """
    errors = ADDRESS_ERRORS | set(NOT_FOUND_ERRORS.values())
    texts = _load(language)["config"]["error"]
    assert {e for e in errors if not texts.get(e)} == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_step_of_the_address_flow_has_its_texts(language):
    """The menu, the address form and the selects have a title and their fields."""
    steps = _load(language)["config"]["step"]
    assert {s for s in ADDRESS_STEPS if not steps.get(s, {}).get("title")} == set()

    menu = steps["yasno_method"]
    assert set(menu["menu_options"]) == {"address", "group"}
    assert set(menu["menu_option_descriptions"]) == {"address", "group"}
    assert set(steps["address"]["data"]) == {"city", "street"}
    for level in ("city", "street"):
        assert set(steps[f"pick_{level}"]["data"]) == {level}
    assert set(steps["house"]["data"]) == {"house"}


def _search_again_texts(language: str) -> dict[str, str]:
    """
    Return the text of the option that searches again, for each translation key.

    The frontend takes the text of an option of a select from the section of the
    select, by the translation key of the select.
    """
    selector = _load(language)["selector"]
    return {
        key: selector.get(key, {}).get("options", {}).get(SEARCH_AGAIN, "")
        for key, _ in SEARCH_AGAIN_TEXTS.values()
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_search_again_option_has_a_text(language):
    """The section of each select has the text of its option that searches again."""
    texts = _search_again_texts(language)
    assert texts  # the table of the flow has the selects
    assert {key for key, text in texts.items() if not text} == set()


def test_search_again_fallback_is_the_english_text():
    """The label that the flow gives the option is the English text of en.json."""
    assert dict(SEARCH_AGAIN_TEXTS.values()) == _search_again_texts("en")


def test_address_texts_name_the_placeholders_that_the_flow_sends():
    """
    The flow sends the page, the address, the counts and the query, and the group.

    The group goes to the text of an error and to the text of the created entry.
    """
    config = _load("en")["config"]
    assert _placeholders(config["step"]["address"]["description"]) == {"url"}
    for level in ("city", "street"):
        text = config["step"][f"pick_{level}"]["description"]
        assert _placeholders(text) == {"place", "count", "query"}
    assert _placeholders(config["step"]["house"]["description"]) == {"place", "count"}
    assert _placeholders(config["error"]["address_group_not_listed"]) == {"group"}
    assert _placeholders(config["create_entry"]["address"]) == {"address", "group"}
