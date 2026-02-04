from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpecMeta:
    spec_id: str
    title: str | None
    version: str | None
    description: str | None
    file_path: str
    operation_count: int
    schema_count: int
    is_valid: bool
    validation_error: str | None


@dataclass(frozen=True)
class Operation:
    spec_id: str
    operation_id: str | None
    method: str
    path: str
    summary: str | None
    description: str | None
    tags: list[str]
    operation: dict[str, Any]

    @property
    def op_key(self) -> str:
        if self.operation_id:
            return f"{self.spec_id}:{self.operation_id}"
        return f"{self.spec_id}:{self.method}:{self.path}"


@dataclass(frozen=True)
class Schema:
    spec_id: str
    schema_name: str
    description: str | None
    schema: dict[str, Any]

    @property
    def schema_key(self) -> str:
        return f"{self.spec_id}:{self.schema_name}"
