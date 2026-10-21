"""Tests for the blueprint that pushes a new Yasno group of an address to a phone."""

from pathlib import Path

from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.util.yaml import load_yaml_dict

from custom_components.svitlo_yeah.const import DOMAIN, EVENT_GROUP_CHANGED

BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints"
    / "automation"
    / DOMAIN
    / "yasno_group_changed.yaml"
)


def _blueprint() -> Blueprint:
    """Load the blueprint as Home Assistant does, with its schema."""
    return Blueprint(
        load_yaml_dict(BLUEPRINT),
        path=str(BLUEPRINT),
        expected_domain="automation",
        schema=BLUEPRINT_SCHEMA,
    )


def test_home_assistant_accepts_the_blueprint():
    """The schema of Home Assistant accepts it, with the inputs that README names."""
    blueprint = _blueprint()

    assert set(blueprint.inputs) == {"notify_device", "entry", "title", "message"}


def test_blueprint_listens_to_the_event_of_a_new_group():
    """The trigger is the event that the coordinator fires after a new group."""
    assert _blueprint().data["triggers"] == [
        {"trigger": "event", "event_type": EVENT_GROUP_CHANGED}
    ]


def test_templates_read_the_keys_of_the_event():
    """
    The templates read the keys that the event has.

    The event has no address, so the name of the entry comes from its id.
    """
    text = BLUEPRINT.read_text(encoding="utf-8")

    for key in ("config_entry_id", "old_group", "new_group"):
        assert f"trigger.event.data.{key}" in text
    assert "config_entry_attr(trigger.event.data.config_entry_id, 'title')" in text
