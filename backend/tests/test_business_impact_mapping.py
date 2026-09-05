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
from app.problem_aggregation import build_problem_mapping_key

EXPECTED_CONFIRMED_MAPPINGS = [
    (
        "After-sales",
        "The response instructs the user to ship a swollen and cracked lithium "
        "power bank via ordinary after-sales parcel, contrary to the explicit "
        "prohibition in the reference evidence, and omits the required stop and "
        "safe disposal guidance.",
        BusinessImpact.HIGH,
    ),
    (
        "After-sales",
        "Response advises continued use of the water despite persistent odor "
        "after required flushing, contrary to the reference that drinking should "
        "stop and system be checked.",
        BusinessImpact.HIGH,
    ),
    (
        "After-sales",
        "The response unnecessarily asks the user to resend order and tracking "
        "numbers that are already available in the associated after-sales record, "
        "leaving the user's core task unresolved despite sufficient information "
        "in the case.",
        BusinessImpact.MEDIUM,
    ),
    (
        "Logistics",
        "The assistant advises the user that the food is likely edible based on "
        "residual coolness, when temperature control cannot be confirmed, creating "
        "a food safety risk.",
        BusinessImpact.HIGH,
    ),
    (
        "Logistics",
        "The response omits the available logistics check option after 72 hours "
        "without tracking updates, potentially delaying issue resolution, but the "
        "core message remains usable.",
        BusinessImpact.MEDIUM,
    ),
    (
        "Logistics",
        "承运商需确认的暂存期限被表述为两天暂存和不会提前退回的确定承诺。",
        BusinessImpact.MEDIUM,
    ),
    (
        "Product",
        "The assistant claims the earbuds can stay connected to two devices "
        "simultaneously and switch audio between them, but the reference states "
        "NovaBuds Lite does not support concurrent connections. Relying on this "
        "answer could lead the user to expect unsupported functionality and cause "
        "confusion or incorrect usage.",
        BusinessImpact.MEDIUM,
    ),
    (
        "Product",
        "The response claims the humidifier has antibacterial features and is "
        "suitable for newborn rooms, which is not supported by the reference "
        "evidence and could lead to unsafe use in a sensitive environment.",
        BusinessImpact.HIGH,
    ),
    (
        "Product",
        "The response overstates that the physical sofa is overall close to dark "
        "green and that lighting differences usually cause only slight variation, "
        "when the reference indicates a more balanced gray-green with "
        "lighting-dependent shifts. This does not fully resolve the user's concern "
        "about green versus gray and could lead to a slightly misleading color "
        "expectation.",
        BusinessImpact.LOW,
    ),
    (
        "Refund",
        "The assistant asked the user to provide information already available in "
        "the session: the order number, payment screenshot, phone number, and "
        "refund application screenshot. The business context shows the session is "
        "already linked to order NM202608304821, and the refund status is "
        "available. The request for redundant information leaves the user's task "
        "(checking refund progress) unresolved.",
        BusinessImpact.MEDIUM,
    ),
    (
        "Refund",
        "The assistant incorrectly tells the user that the refund will return to "
        "their own account, when the case facts and reference indicate that for a "
        "friend-paid order, the refund is returned to the actual payer's account.",
        BusinessImpact.HIGH,
    ),
    (
        "Refund",
        "The response instructs the user to submit a seven-day no-reason return "
        "based on actual pickup date and suggests it will generally be calculated "
        "from that date, directly contradicting the reference rule that the period "
        "starts from logistics signing record and disputed signing requires "
        "verification or escalation.",
        BusinessImpact.HIGH,
    ),
    (
        "Refund",
        "用户询问两件商品使用20元优惠券后部分退款时,券和钱如何计算。"
        "助手回应优惠券会在退款完成后返还到券包,这与业务规则“已核销优惠券"
        "不因部分退款返还”相矛盾,用户按此信息操作将错误预期优惠券返还。",
        BusinessImpact.MEDIUM,
    ),
]


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


def test_versioned_asset_loads_all_confirmed_exact_mappings() -> None:
    mapping = load_business_impact_mapping()
    service = BusinessImpactMappingService(mapping)

    assert BUSINESS_IMPACT_MAPPING_PATH.is_file()
    assert mapping.mapping_version == BUSINESS_IMPACT_MAPPING_VERSION
    assert len(mapping.mappings) == 13
    for scenario, definition, expected_impact in EXPECTED_CONFIRMED_MAPPINGS:
        result = service.lookup(
            build_problem_mapping_key(scenario, definition)
        )
        assert result.status == BusinessImpactLookupStatus.MAPPED
        assert result.business_impact is expected_impact


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
