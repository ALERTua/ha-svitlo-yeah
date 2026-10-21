"""Models for Svitlo Yeah."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from custom_components.svitlo_yeah.const import CONF_CITY, CONF_HOUSE, CONF_STREET

from .providers import SoeProvider, YasnoProvider

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Mapping

__all__ = [
    "ConnectivityState",
    "PlannedOutageEvent",
    "PlannedOutageEventType",
    "SoeProvider",
    "YasnoAddress",
    "YasnoAddressItem",
    "YasnoPlannedOutageDayStatus",
    "YasnoProvider",
    "YasnoRegion",
]


class YasnoPlannedOutageDayStatus(StrEnum):
    """Outage day status."""

    STATUS_SCHEDULE_APPLIES = "ScheduleApplies"
    STATUS_WAITING_FOR_SCHEDULE = "WaitingForSchedule"
    STATUS_EMERGENCY_SHUTDOWNS = "EmergencyShutdowns"


class PlannedOutageEventType(StrEnum):
    """Outage event types."""

    DEFINITE = "Definite"
    NOT_PLANNED = "NotPlanned"
    EMERGENCY = "Emergency"
    # This one does not exist in the API
    # It is only to create scheduled events
    SCHEDULED = "Scheduled"


class ConnectivityState(StrEnum):
    """Connectivity state."""

    STATE_EMERGENCY = "emergency"
    STATE_NORMAL = "normal"
    STATE_PLANNED_OUTAGE = "planned_outage"


@dataclass(frozen=True)
class PlannedOutageEvent:
    """Represents an outage event."""

    event_type: PlannedOutageEventType
    start: dt.datetime | dt.date
    end: dt.datetime | dt.date
    all_day: bool = False


@dataclass
class YasnoRegion:
    """Yasno region data."""

    id: int  # 25
    name: str  # Київ
    dsos: list[YasnoProvider] = field(default_factory=list)
    # Whether an address in the region has a city, for example in Дніпро. A stored
    # region of an older version has no such key.
    has_cities: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> YasnoRegion:
        """Create instance from dict data."""
        output = cls(
            id=data["id"],
            name=data["value"],
            has_cities=data.get("hasCities") is True,
        )
        output.dsos = [
            YasnoProvider.from_dict(
                data=_, region_id=output.id, region_name=output.name
            )
            for _ in data["dsos"]
        ]
        return output


@dataclass(frozen=True)
class YasnoAddressItem:
    """One match of a Yasno search of a city, a street or a house."""

    id: int  # 1647
    value: str  # вул. Сверстюка Євгена


@dataclass(frozen=True)
class YasnoAddress:
    """The names of an address, as Yasno writes them."""

    street: str  # вул. Сверстюка Євгена
    house: str  # the number with its letter, as Yasno writes it
    # Only a region with cities has it, for example «м. Дніпро»
    city: str | None = None

    @classmethod
    def from_entry_data(cls, data: Mapping[str, Any]) -> YasnoAddress | None:
        """Return the address of an entry, or None for an entry with a group only."""
        street, house = data.get(CONF_STREET), data.get(CONF_HOUSE)
        if not street or not house:
            return None
        return cls(street=street, house=house, city=data.get(CONF_CITY))

    @property
    def text(self) -> str:
        """
        Return the address as one name, for the entry and the device.

        «вул. Сверстюка Євгена, 1», or «м. Дніпро, вул. Грушевського Михайла, 1».
        """
        parts = (self.city, self.street, self.house)
        # Yasno writes some names with a space at the end
        return ", ".join(part.strip() for part in parts if part)
