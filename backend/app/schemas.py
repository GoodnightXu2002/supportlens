from datetime import datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetSource(StrEnum):
    USER_UPLOAD = "user_upload"
    FIXTURE_IMPORT = "fixture_import"


class PrivacyStatus(StrEnum):
    SYNTHETIC = "synthetic"
    DEIDENTIFIED = "deidentified"
    MAY_CONTAIN_PERSONAL_DATA = "may_contain_personal_data"
    UNKNOWN = "unknown"


class DatasetBase(BaseModel):
    name: str
    description: str | None = None
    version: str = "v1.0"
    source: DatasetSource
    privacy_status: PrivacyStatus = PrivacyStatus.UNKNOWN
    representativeness_statement: str | None = None

    @model_validator(mode="after")
    def validate_fixture_import_contract(self) -> Self:
        if self.source is not DatasetSource.FIXTURE_IMPORT:
            return self
        if self.privacy_status is not PrivacyStatus.SYNTHETIC:
            raise ValueError("fixture_import requires privacy_status=synthetic")
        if not self.representativeness_statement or not (
            self.representativeness_statement.strip()
        ):
            raise ValueError(
                "fixture_import requires a non-empty "
                "representativeness_statement"
            )
        return self


class DatasetCreate(DatasetBase):
    pass


class DatasetRead(DatasetBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class ConversationBase(BaseModel):
    external_id: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any] | None = None


class ConversationCreate(ConversationBase):
    pass


class ConversationRead(ConversationBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    dataset_id: UUID
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime


class DatasetImportConfirmRequest(BaseModel):
    import_token: str


class DatasetImportConfirmResponse(BaseModel):
    dataset_id: UUID
    name: str
    version: str
    source: DatasetSource
    privacy_status: PrivacyStatus
    representativeness_statement: str | None
    conversation_count: int
    created_at: datetime


class DatasetListItem(BaseModel):
    dataset_id: UUID
    name: str
    description: str | None
    version: str
    source: DatasetSource
    privacy_status: PrivacyStatus
    representativeness_statement: str | None
    conversation_count: int
    created_at: datetime


class DatasetDetailResponse(DatasetListItem):
    scenario_distribution: dict[str, int]


class DatasetConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    external_id: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="metadata_",
    )
    created_at: datetime
