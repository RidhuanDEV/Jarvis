"""Strict Pydantic v2 Tool Argument Validation Schemas (B14, eliminating KeyError 500s across all tools)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class _StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemTimeArgs(_StrictToolArgs):
    timezone_iana: str | None = Field(default=None, min_length=2, max_length=64)


class OsVolumeSetArgs(_StrictToolArgs):
    percent: int = Field(ge=0, le=100)


class OsAppLaunchArgs(_StrictToolArgs):
    app_id: str = Field(min_length=1, max_length=128)
    target: str | None = Field(default=None, max_length=512)


class FsMetadataSearchArgs(_StrictToolArgs):
    query: str = Field(default="", max_length=256)
    ext: str | None = Field(default=None, max_length=16)
    recent: bool = False
    limit: int = Field(default=5, ge=1, le=50)


class FsFileOpenArgs(_StrictToolArgs):
    file_query: str | None = Field(default=None, min_length=1, max_length=256)
    result_index: int | None = Field(default=None, ge=1, le=50)

    @model_validator(mode="after")
    def _require_target(self) -> FsFileOpenArgs:
        if self.file_query is None and self.result_index is None:
            raise ValueError("Either 'file_query' or 'result_index' is required.")
        return self


class FsFileMoveArgs(_StrictToolArgs):
    source_relative_path: str | None = Field(default=None, min_length=1, max_length=512)
    target_relative_path: str | None = Field(default=None, min_length=1, max_length=512)
    src: str | None = Field(default=None, min_length=1, max_length=512)
    dst: str | None = Field(default=None, min_length=1, max_length=512)
    source_path: str | None = Field(default=None, min_length=1, max_length=512)
    target_path: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _require_src_dst(self) -> FsFileMoveArgs:
        has_src = any(v is not None for v in (self.source_relative_path, self.src, self.source_path))
        has_dst = any(v is not None for v in (self.target_relative_path, self.dst, self.target_path))
        if not (has_src and has_dst):
            raise ValueError("Both source and target paths are required for fs.file.move.")
        return self


class FsFileEditArgs(_StrictToolArgs):
    root_id: str = Field(min_length=1, max_length=128)
    relative_path: str = Field(min_length=1, max_length=512)
    new_content: str = Field(min_length=1, max_length=200_000)


class MemoryCreateArgs(_StrictToolArgs):
    kind: Literal["fact", "preference", "instruction", "note"] = "fact"
    content: str = Field(min_length=1, max_length=4000)
    sensitivity: Literal["normal", "sensitive"] = "normal"


class ReminderCreateArgs(_StrictToolArgs):
    title: str = Field(min_length=1, max_length=300)
    due_at_utc: datetime
    timezone_iana: str | None = Field(default=None, min_length=2, max_length=64)


class LifeTaskCreateArgs(_StrictToolArgs):
    title: str = Field(min_length=1, max_length=300)


class LifeTaskListArgs(_StrictToolArgs):
    pass


class KnowledgeQueryArgs(_StrictToolArgs):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class ScreenAnalyzeArgs(_StrictToolArgs):
    window_selector: str = Field(default="active", min_length=1, max_length=256)


class WebSearchQueryArgs(_StrictToolArgs):
    q: str | None = Field(default=None, min_length=1, max_length=500)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    url: str | None = Field(default=None, min_length=8, max_length=2048)

    @model_validator(mode="after")
    def _require_query_or_url(self) -> WebSearchQueryArgs:
        if not any((self.q, self.query, self.url)):
            raise ValueError("One of 'q', 'query', or 'url' is required.")
        return self


_TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "system.time.get": SystemTimeArgs,
    "os.volume.set": OsVolumeSetArgs,
    "os.app.launch": OsAppLaunchArgs,
    "fs.metadata.search": FsMetadataSearchArgs,
    "fs.file.open": FsFileOpenArgs,
    "fs.file.move": FsFileMoveArgs,
    "fs.file.edit": FsFileEditArgs,
    "memory.create": MemoryCreateArgs,
    "reminder.create": ReminderCreateArgs,
    "life.task.create": LifeTaskCreateArgs,
    "life.task.list": LifeTaskListArgs,
    "knowledge.query": KnowledgeQueryArgs,
    "screen.analyze": ScreenAnalyzeArgs,
    "web.search.query": WebSearchQueryArgs,
}


def validate_tool_step_args(
    tool_id: str, args: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and normalize tool arguments strictly before dispatch (zero KeyError 500s, B14)."""
    schema_cls = _TOOL_ARG_SCHEMAS.get(tool_id)
    if schema_cls is None:
        return (dict(args), None)
    try:
        validated = schema_cls.model_validate(args)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        msg = str(first.get("msg", "invalid argument"))
        return (None, f"Argumen tool '{tool_id}' tidak valid ({loc or 'args'}): {msg}")
    dumped = validated.model_dump(mode="json", exclude_none=True)
    return (dumped, None)
