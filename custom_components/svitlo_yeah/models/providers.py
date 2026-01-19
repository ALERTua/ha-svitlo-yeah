"""Providers module for Svitlo Yeah."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from typing import Self

from ..const import PROVIDER_TYPE_DTEK_JSON, PROVIDER_TYPE_E_SVITLO, PROVIDER_TYPE_YASNO


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseProvider(ABC):
    """Base class for provider models."""

    region_name: str
    region_id: int | None = None

    @property
    @abstractmethod
    def unique_key(self) -> str:
        """Subclasses must implement this property."""
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_id(self) -> str | int:
        """Subclasses must implement this property."""
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Subclasses must implement this property."""
        raise NotImplementedError

    @property
    def translation_key(self) -> str:
        """Get translation key for this provider."""
        return self.unique_key


@dataclass(frozen=True, kw_only=True)
class ESvitloProvider(BaseProvider):
    """E-Svitlo provider model."""

    user_name: str
    password: str
    region_name: str = "sumy"
    account_id: int | str | None = None
    provider_type: str = PROVIDER_TYPE_E_SVITLO

    @cached_property
    def unique_key(self) -> str:
        """Generate unique key for this provider."""
        return f"{self.__class__.__name__.lower()}_{self.region_name}"

    @cached_property
    def provider_id(self) -> str:
        """Provider ID."""
        return self.user_name


@dataclass(frozen=True, kw_only=True)
class YasnoProvider(BaseProvider):
    """Yasno provider model."""

    id: int
    name: str
    region_name: str
    region_id: int | None = None
    provider_type: str = PROVIDER_TYPE_YASNO

    @cached_property
    def unique_key(self) -> str:
        """Generate unique key for this provider."""
        return f"{self.__class__.__name__.lower()}_{self.region_id}_{self.id}"

    @cached_property
    def provider_id(self) -> int:
        """Provider ID."""
        return self.id

    @classmethod
    def from_dict(cls, data: dict, region_id: int, region_name: str) -> Self:
        """Create instance from dict data."""
        return cls(**data, region_id=region_id, region_name=region_name)


@dataclass(frozen=True, kw_only=True)
class DTEKJsonProvider(BaseProvider):
    """DTEK provider for DTEK JSON API."""

    region_name: str
    provider_type: str = PROVIDER_TYPE_DTEK_JSON

    @cached_property
    def unique_key(self) -> str:
        """Generate unique key for this provider."""
        return f"{self.__class__.__name__.lower()}_{self.region_name}"

    @cached_property
    def provider_id(self) -> str:
        """Provider ID."""
        return self.region_name
