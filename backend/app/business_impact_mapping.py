from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

BUSINESS_IMPACT_MAPPING_VERSION = "BUSINESS-IMPACT-MAPPING-V1"
BUSINESS_IMPACT_MAPPING_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "business_impact_mapping_v1.json"
)


class _StrictMappingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusinessImpact(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BusinessImpactLookupStatus(StrEnum):
    MAPPED = "mapped"
    UNMAPPED = "unmapped"


class BusinessImpactMappingEntry(_StrictMappingModel):
    mapping_key: str
    business_impact: BusinessImpact

    @field_validator("mapping_key")
    @classmethod
    def mapping_key_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("mapping_key must not be blank")
        return value


class BusinessImpactMappingAsset(_StrictMappingModel):
    mapping_version: Literal["BUSINESS-IMPACT-MAPPING-V1"]
    mappings: list[BusinessImpactMappingEntry]

    @model_validator(mode="after")
    def mapping_keys_must_be_unique(self) -> BusinessImpactMappingAsset:
        mapping_keys = [entry.mapping_key for entry in self.mappings]
        if len(mapping_keys) != len(set(mapping_keys)):
            raise ValueError("mapping_key values must be unique")
        return self


class BusinessImpactLookupResult(_StrictMappingModel):
    mapping_key: str
    mapping_version: Literal["BUSINESS-IMPACT-MAPPING-V1"]
    status: BusinessImpactLookupStatus
    business_impact: BusinessImpact | None


def load_business_impact_mapping(
    path: Path = BUSINESS_IMPACT_MAPPING_PATH,
) -> BusinessImpactMappingAsset:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BusinessImpactMappingAsset.model_validate(payload)


class BusinessImpactMappingService:
    def __init__(self, mapping: BusinessImpactMappingAsset | None = None) -> None:
        self._mapping = mapping or load_business_impact_mapping()
        self._business_impact_by_key = {
            entry.mapping_key: entry.business_impact
            for entry in self._mapping.mappings
        }

    @property
    def mapping_version(self) -> str:
        return self._mapping.mapping_version

    def lookup(self, mapping_key: str) -> BusinessImpactLookupResult:
        business_impact = self._business_impact_by_key.get(mapping_key)
        status = (
            BusinessImpactLookupStatus.MAPPED
            if business_impact is not None
            else BusinessImpactLookupStatus.UNMAPPED
        )
        return BusinessImpactLookupResult(
            mapping_key=mapping_key,
            mapping_version=self._mapping.mapping_version,
            status=status,
            business_impact=business_impact,
        )
