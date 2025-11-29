"""Providers module for Svitlo Yeah."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
        from ..const import PROVIDER_TYPE_YASNO  # noqa: PLC0415

        return PROVIDER_TYPE_YASNO


class DTEKJsonProvider(BaseProvider, StrEnum):
    """DTEK provider for DTEK JSON API."""

    KYIV_REGION = "kyiv_region"
    DNIPRO = "dnipro"
    ODESA = "odesa"
    KHMELNYTSKYI = "khmelnytskyi"
    IVANO_FRANKIVSK = "ivano_frankivsk"
    UZHHOROD = "uzhhorod"
    LVIV = "lviv"

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
        from ..const import PROVIDER_TYPE_DTEK_JSON  # noqa: PLC0415

        return PROVIDER_TYPE_DTEK_JSON
