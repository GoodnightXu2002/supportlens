import json

import pytest
from pydantic import ValidationError

from app.business_impact_mapping import (
    BUSINESS_IMPACT_MAPPING_PATH,
    BUSINESS_IMPACT_MAPPING_VERSION,
    BusinessImpact,
    BusinessImpactLookupStatus,
    BusinessImpactMappingAsset,
    BusinessImpactMappingService,
    load_business_impact_mapping,
)


def _mapping_payload(entries: list[dict[str, str]]) -> dict[str, object]:
    return {
        "mapping_version": BUSINESS_IMPACT_MAPPING_VERSION,
        "mappings": entries,
    }


@pytest.mark.parametrize("business_impact", ["high", "medium", "low"])
def test_mapping_accepts_frozen_business_impact_values(
    business_impact: str,
) -> None:
    mapping = BusinessImpactMappingAsset.model_validate(
        _mapping_payload(
            [
                {
                    "mapping_key": '["Refund","Explicit problem"]',
                    "business_impact": business_impact,
                }
            ]
        )
    )

    assert mapping.mappings[0].business_impact == BusinessImpact(business_impact)


def test_mapping_rejects_value_outside_frozen_enum() -> None:
    with pytest.raises(ValidationError):
        BusinessImpactMappingAsset.model_validate(
            _mapping_payload(
                [
                    {
                        "mapping_key": '["Refund","Explicit problem"]',
                        "business_impact": "critical",
                    }
                ]
            )
        )


def test_versioned_asset_loads_with_frozen_version_and_no_assumed_values() -> None:
    mapping = load_business_impact_mapping()

    assert BUSINESS_IMPACT_MAPPING_PATH.is_file()
    assert mapping.mapping_version == BUSINESS_IMPACT_MAPPING_VERSION
    assert mapping.mappings == []


def test_loader_rejects_incorrect_mapping_version(tmp_path) -> None:
    mapping_path = tmp_path / "business-impact.json"
    mapping_path.write_text(
        json.dumps(
            {
                "mapping_version": "BUSINESS-IMPACT-MAPPING-V2",
                "mappings": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_business_impact_mapping(mapping_path)


def test_lookup_returns_explicit_mapped_business_impact() -> None:
    mapping_key = '["Refund","Explicit problem"]'
    mapping = BusinessImpactMappingAsset.model_validate(
        _mapping_payload(
            [{"mapping_key": mapping_key, "business_impact": "high"}]
        )
    )

    result = BusinessImpactMappingService(mapping).lookup(mapping_key)

    assert result.mapping_key == mapping_key
    assert result.mapping_version == BUSINESS_IMPACT_MAPPING_VERSION
    assert result.status == BusinessImpactLookupStatus.MAPPED
    assert result.business_impact == BusinessImpact.HIGH


def test_unmapped_lookup_returns_no_business_impact() -> None:
    result = BusinessImpactMappingService().lookup(
        '["Critical scenario","high severity failure"]'
    )

    assert result.mapping_version == BUSINESS_IMPACT_MAPPING_VERSION
    assert result.status == BusinessImpactLookupStatus.UNMAPPED
    assert result.business_impact is None


def test_lookup_is_exact_and_does_not_infer_from_similar_mapping_key() -> None:
    mapped_key = '["Refund","Agent omitted required step"]'
    mapping = BusinessImpactMappingAsset.model_validate(
        _mapping_payload(
            [{"mapping_key": mapped_key, "business_impact": "medium"}]
        )
    )
    service = BusinessImpactMappingService(mapping)

    result = service.lookup('["Refund","Agent omitted required steps"]')

    assert result.status == BusinessImpactLookupStatus.UNMAPPED
    assert result.business_impact is None
