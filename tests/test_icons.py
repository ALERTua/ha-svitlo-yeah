"""The entities take their icons from icons.json (gold icon-translations), and the integration ships its brand images."""

import json
import re
import struct
from pathlib import Path

from custom_components.svitlo_yeah.button import REFRESH_BUTTON
from custom_components.svitlo_yeah.models import ConnectivityState
from custom_components.svitlo_yeah.sensor import SENSORS

ROOT = Path(__file__).parent.parent
ICONS = json.loads(
    (ROOT / "custom_components/svitlo_yeah/icons.json").read_text(encoding="utf-8")
)["entity"]
MDI = re.compile(r"^mdi:[a-z0-9-]+$")
BRAND = ROOT / "custom_components/svitlo_yeah/brand"


def _png_size(path: Path) -> tuple[int, int]:
    """Read the width and the height from the header of a PNG file."""
    return struct.unpack(">II", path.read_bytes()[16:24])


def test_no_description_sets_an_icon():
    """An icon of the description would hide the icons of icons.json."""
    assert [d.key for d in (*SENSORS, REFRESH_BUTTON) if d.icon] == []


def test_each_entity_has_an_icon_and_each_icon_an_entity():
    """icons.json has an entry for each translation key, and no other entry."""
    assert set(ICONS["sensor"]) == {d.translation_key for d in SENSORS}
    assert set(ICONS["button"]) == {REFRESH_BUTTON.translation_key}
    icons = [
        icon
        for platform in ICONS.values()
        for entry in platform.values()
        for icon in (entry["default"], *entry.get("state", {}).values())
    ]
    assert [icon for icon in icons if not MDI.match(icon)] == []


def test_electricity_shows_each_outage_with_its_own_icon():
    """An outage looks different from the power that is on, and each kind of outage differs."""
    electricity = ICONS["sensor"]["electricity"]
    states = electricity["state"]

    assert set(states) <= {str(state) for state in ConnectivityState}
    assert len({electricity["default"], *states.values()}) == 3
    assert ConnectivityState.STATE_NORMAL not in states  # the default icon


def test_brand_folder_has_the_images_of_the_integration():
    """The brand folder gives Home Assistant and HACS the icon and the logo of the integration."""
    names = {"icon.png", "icon@2x.png", "logo.png", "logo@2x.png"}

    assert {path.name for path in BRAND.iterdir()} == names
    assert _png_size(BRAND / "icon.png") == (256, 256)
    assert _png_size(BRAND / "icon@2x.png") == (512, 512)
    # The README and the release notes show the copies in icons/
    assert [
        n
        for n in names
        if (BRAND / n).read_bytes() != (ROOT / "icons" / n).read_bytes()
    ] == []
