"""Pydantic models shared across the backend.

The schema-introspection models below are the canonical representation of a
database's structure. The prompt engine (Week 2) consumes DatabaseSchema to
build schema-aware prompts; the API returns these to the frontend.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    is_nullable: bool
    default: str | None = None
    ordinal: int
    is_primary_key: bool = False


class ForeignKey(BaseModel):
    name: str
    columns: list[str]                 # local columns
    referred_schema: str
    referred_table: str
    referred_columns: list[str]        # columns in the referenced table


class TableSchema(BaseModel):
    schema_name: str
    name: str
    columns: list[ColumnInfo]
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    row_count: int | None = None
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.name}"


class DatabaseSchema(BaseModel):
    schema_name: str
    tables: list[TableSchema]

    def table(self, name: str) -> TableSchema | None:
        return next((t for t in self.tables if t.name == name), None)
