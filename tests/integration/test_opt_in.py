import pytest


@pytest.mark.integration
def test_integration_suite_is_opt_in() -> None:
    """Keep the integration marker exercised before live suites are added."""
