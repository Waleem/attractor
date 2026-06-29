from __future__ import annotations

from attractor_platform.errors import (
    AttractorPlatformError,
    ConfigLoadError,
    PlatformErrorCode,
    WorkflowPackageError,
)


def test_platform_error_has_stable_code_and_detail() -> None:
    err = WorkflowPackageError(
        "workflow.dot is required",
        detail={"workflow": "release-checks"},
    )

    assert err.code == PlatformErrorCode.WORKFLOW_PACKAGE_INVALID
    assert str(err) == "workflow.dot is required"
    assert err.detail == {"workflow": "release-checks"}
    assert err.to_dict() == {
        "code": "workflow_package_invalid",
        "message": "workflow.dot is required",
        "detail": {"workflow": "release-checks"},
    }


def test_specific_errors_are_platform_errors() -> None:
    assert issubclass(ConfigLoadError, AttractorPlatformError)
    assert issubclass(WorkflowPackageError, AttractorPlatformError)
