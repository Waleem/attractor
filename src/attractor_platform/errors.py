"""Platform-facing error contracts for Attractor.

These exceptions are intentionally small and stable. They are safe to expose
through future API responses without binding the server to internal Python
exception types from parser, validation, or execution modules.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class PlatformErrorCode(StrEnum):
    """Stable machine-readable error codes for platform operations."""

    CONFIG_LOAD_FAILED = "config_load_failed"
    WORKFLOW_PACKAGE_INVALID = "workflow_package_invalid"
    RUN_SPEC_INVALID = "run_spec_invalid"
    GIT_METADATA_UNAVAILABLE = "git_metadata_unavailable"


class AttractorPlatformError(Exception):
    """Base class for platform contract failures."""

    code: PlatformErrorCode = PlatformErrorCode.CONFIG_LOAD_FAILED

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation suitable for API responses."""
        return {
            "code": self.code.value,
            "message": self.message,
            "detail": self.detail,
        }


class ConfigLoadError(AttractorPlatformError):
    """Raised when project or workflow TOML cannot be loaded."""

    code = PlatformErrorCode.CONFIG_LOAD_FAILED


class WorkflowPackageError(AttractorPlatformError):
    """Raised when a repo-local workflow package is missing or invalid."""

    code = PlatformErrorCode.WORKFLOW_PACKAGE_INVALID


class RunSpecError(AttractorPlatformError):
    """Raised when an immutable run manifest cannot be built."""

    code = PlatformErrorCode.RUN_SPEC_INVALID


class GitMetadataError(AttractorPlatformError):
    """Raised when required git metadata cannot be read."""

    code = PlatformErrorCode.GIT_METADATA_UNAVAILABLE
