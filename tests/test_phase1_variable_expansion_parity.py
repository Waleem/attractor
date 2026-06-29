from __future__ import annotations

import pytest

from attractor_pipeline.variable_expansion import expand_variables


def test_bare_and_braced_variables_expand_scalars() -> None:
    result = expand_variables(
        "Build $service version ${version} approved=$approved",
        {"service": "billing", "version": "1.2.3", "approved": True},
    )

    assert result == "Build billing version 1.2.3 approved=True"


def test_escaped_dollar_is_preserved_as_literal_dollar() -> None:
    result = expand_variables(r"Cost is \$5 and service is $service", {"service": "billing"})

    assert result == "Cost is $5 and service is billing"


def test_undefined_variables_are_kept_by_default() -> None:
    assert expand_variables("Hello $name", {}) == "Hello $name"


def test_undefined_variables_can_be_emptied() -> None:
    assert expand_variables("Hello $name", {}, undefined="empty") == "Hello "


def test_undefined_variables_can_raise() -> None:
    with pytest.raises(KeyError, match="Undefined variable"):
        expand_variables("Hello $name", {}, undefined="error")


def test_dotted_variable_names_are_single_lookup_keys() -> None:
    result = expand_variables(
        "Deploy $service.name",
        {"service.name": "billing-api", "service": "billing"},
    )

    assert result == "Deploy billing-api"


def test_nested_expansion_is_not_recursive() -> None:
    result = expand_variables("$outer", {"outer": "$inner", "inner": "value"})

    assert result == "$inner"


def test_non_scalar_values_are_not_expanded() -> None:
    result = expand_variables("Items: $items", {"items": ["a", "b"]})

    assert result == "Items: $items"
