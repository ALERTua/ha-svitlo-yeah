"""Models for Svitlo Yeah."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from .const import PROVIDER_TYPE_DTEK_HTML, PROVIDER_TYPE_DTEK_JSON, PROVIDER_TYPE_YASNO

if TYPE_CHECKING:
    import datetime


class YasnoPlannedOutageDayStatus(StrEnum):
    """Outage day status."""

    STATUS_SCHEDULE_APPLIES = "ScheduleApplies"
    STATUS_EMERGENCY_SHUTDOWNS = "EmergencyShutdowns"


class PlannedOutageEventType(StrEnum):
    """Outage event types."""

    DEFINITE = "Definite"
    NOT_PLANNED = "NotPlanned"
    EMERGENCY = "Emergency"


class ConnectivityState(StrEnum):
    """Connectivity state."""

    STATE_EMERGENCY = "emergency"
    STATE_NORMAL = "normal"
    STATE_PLANNED_OUTAGE = "planned_outage"


@dataclass(frozen=True)
class PlannedOutageEvent:
    """Represents an outage event."""

    event_type: PlannedOutageEventType
    start: datetime.datetime | datetime.date
    end: datetime.datetime | datetime.date
    all_day: bool = False


class BaseProvider:
    """Base class for provider models."""

    region_id: int | None = None

    @property
    def unique_key(self) -> str:
        """Subclasses must implement this property."""
        raise NotImplementedError

    @property
    def provider_id(self) -> str:
        """Subclasses must implement this property."""
        raise NotImplementedError

    @property
    def provider_type(self) -> str:
        """Subclasses must implement this property."""
        raise NotImplementedError

    @property
    def translation_key(self) -> str:
        """Get translation key for this provider."""
        return self.unique_key


@dataclass(frozen=True)
class YasnoProvider(BaseProvider):
    """Yasno provider model."""

    id: int
    name: str
    region_id: int | None

    @property
    def unique_key(self) -> str:
        """Generate unique key for this provider."""
        return f"{self.__class__.__name__.lower()}_{self.region_id}_{self.id}"

    @classmethod
    def from_dict(cls, data: dict, region_id: int) -> YasnoProvider:
        """Create instance from dict data."""
        return cls(**data, region_id=region_id)

    @property
    def provider_id(self) -> int:
        """Provider ID."""
        return self.id

    @property
    def provider_type(self) -> str:
        """Provider type."""
        return PROVIDER_TYPE_YASNO


@dataclass
class YasnoRegion:
    """Yasno region data."""

    has_cities: bool
    id: int  # 25
    value: str  # Київ
    dsos: list[YasnoProvider] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> YasnoRegion:
        """Create instance from dict data."""
        output = cls(has_cities=data["hasCities"], id=data["id"], value=data["value"])
        output.dsos = [
            YasnoProvider.from_dict(_, region_id=output.id) for _ in data["dsos"]
        ]
        return output


class DTEKJsonProvider(BaseProvider, StrEnum):
    """DTEK provider for DTEK JSON API."""

    KYIV_REGION = "kyiv_region"
    DNIPRO = "dnipro"
    ODESA = "odesa"
    KHMELNYTSKYI = "khmelnytskyi"
    IVANO_FRANKIVSK = "ivano_frankivsk"
    UZHHOROD = "uzhhorod"

    @property
    def unique_key(self) -> str:
        """Generate unique key for this provider."""
        return f"{self.__class__.__name__.lower()}_{self.value}"

    @property
    def provider_id(self) -> str:
        """Provider ID."""
        return str(self.value)

    @property
    def provider_type(self) -> str:
        """Provider type."""
        return PROVIDER_TYPE_DTEK_JSON


class DTEKHTMLProvider(BaseProvider):
    """DTEK provider for DTEK HTML API."""

    unique_key = translation_key = provider_id = provider_type = PROVIDER_TYPE_DTEK_HTML


# URL mappings for JSON sources
DTEK_PROVIDER_URLS: dict[DTEKJsonProvider, list[str]] = {
    DTEKJsonProvider.KYIV_REGION: [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/kyiv-region.json",
    ],
    DTEKJsonProvider.DNIPRO: [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/dnipro.json",
    ],
    DTEKJsonProvider.ODESA: [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/odesa.json",
    ],
    DTEKJsonProvider.KHMELNYTSKYI: [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Khmelnytskoblenerho.json",
    ],
    DTEKJsonProvider.IVANO_FRANKIVSK: [
        "https://github.com/yaroslav2901/PRYKARPATTIAOBLENERHO_OUTAGE_DATA/raw/main/data/Ivano-Frankivsk.json",
    ],
    DTEKJsonProvider.UZHHOROD: [
        "https://github.com/yaroslav2901/ZAKARPATTIAOBLENERHO_OUTAGE_DATA/raw/main/data/Zakarpattiaoblenerho.json",
    ],
}
