from backend.src.orchestration.contracts.models import (
    GenericStepOutput,
    validate_output_with_contract,
)


def test_contract_validation_rejects_invalid_payload() -> None:
    ok, payload, error = validate_output_with_contract(
        output_model=GenericStepOutput,
        output={"confidence": 0.4, "artifacts": {}},
    )

    assert ok is False
    assert payload is None
    assert error is not None
