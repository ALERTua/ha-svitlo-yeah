"""Providers module for Svitlo Yeah."""

from __future__ import annotations

from dataclasses import dataclass

from ..const import PROVIDER_TYPE_DTEK_JSON, PROVIDER_TYPE_YASNO


class BaseProvider:
    """Base class for provider models."""

    region_name: str

    @property
    def unique_key(self) -> str:
        """Subclasses must implement this property."""
        raise NotImplementedError

    @property
    def provider_id(self) -> str | int:
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
    region_id: int
    region_name: str

    @property
    def unique_key(self) -> str:
        """Generate unique key for this provider."""
        return f"{self.__class__.__name__.lower()}_{self.region_id}_{self.id}"

    @classmethod
    def from_dict(cls, data: dict, region_id: int, region_name: str) -> YasnoProvider:
        """Create instance from dict data."""
        return cls(**data, region_id=region_id, region_name=region_name)

    @property
    def provider_id(self) -> int:
        """Provider ID."""
        return self.id

    @property
    def provider_type(self) -> str:
        """Provider type."""
        return PROVIDER_TYPE_YASNO


@dataclass(frozen=True)
class DTEKJsonProvider(BaseProvider):
    """DTEK provider for DTEK JSON API."""

    region_name: str

    @property
    def unique_key(self) -> str:
        """Generate unique key for this provider."""
        return f"{self.__class__.__name__.lower()}_{self.region_name}"

    @property
    def provider_id(self) -> str:
        """Provider ID."""
        return self.region_name

    @property
    def provider_type(self) -> str:
        """Provider type."""
        return PROVIDER_TYPE_DTEK_JSON
