from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.import_service import (
    ImportFileValidationError,
    ImportPreviewResult,
    ImportService,
    ImportServiceError,
    ImportServiceErrorCode,
)
from app.models import Conversation, Dataset
from app.schemas import (
    DatasetConversationRead,
    DatasetDetailResponse,
    DatasetImportConfirmRequest,
    DatasetImportConfirmResponse,
    DatasetListItem,
)

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache
def get_import_service() -> ImportService:
    return ImportService()


def get_db_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                }
            }
        ),
    )


def _validation_details(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "field": ".".join(str(part) for part in issue["loc"]),
            "code": issue["type"],
            "message": issue["msg"],
        }
        for issue in error.errors(include_url=False, include_context=False)
    ]


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(part) for part in issue["loc"]),
            "code": issue["type"],
            "message": issue["msg"],
        }
        for issue in error.errors()
    ]
    return _error_response(
        status_code=400,
        code="request_validation_failed",
        message="Request validation failed.",
        details=details,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/dataset-imports/preview",
    response_model=ImportPreviewResult,
)
async def preview_dataset_import(
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    import_service: Annotated[ImportService, Depends(get_import_service)],
    description: Annotated[str | None, Form()] = None,
    version: Annotated[str, Form()] = "v1.0",
    source: Annotated[str, Form()] = "user_upload",
    privacy_status: Annotated[str | None, Form()] = None,
    representativeness_statement: Annotated[str | None, Form()] = None,
) -> ImportPreviewResult | JSONResponse:
    file_data = await file.read()
    try:
        return import_service.preview_import(
            file_data,
            filename=file.filename or "",
            dataset_name=name,
            description=description,
            version=version,
            source=source,
            privacy_status=privacy_status,
            representativeness_statement=representativeness_statement,
        )
    except ImportFileValidationError as error:
        return _error_response(
            status_code=400,
            code="import_validation_failed",
            message="Import file validation failed.",
            details=[
                detail.model_dump(mode="json") for detail in error.errors
            ],
        )
    except ValidationError as error:
        return _error_response(
            status_code=400,
            code="invalid_dataset_identity",
            message="Dataset identity validation failed.",
            details=_validation_details(error),
        )


@app.post(
    "/api/dataset-imports/confirm",
    response_model=DatasetImportConfirmResponse,
)
def confirm_dataset_import(
    request: DatasetImportConfirmRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    import_service: Annotated[ImportService, Depends(get_import_service)],
) -> DatasetImportConfirmResponse | JSONResponse:
    try:
        result = import_service.confirm_import(request.import_token, db_session)
    except ImportServiceError as error:
        status_by_code = {
            ImportServiceErrorCode.IMPORT_TOKEN_NOT_FOUND: 404,
            ImportServiceErrorCode.IMPORT_TOKEN_EXPIRED: 410,
            ImportServiceErrorCode.DATASET_PERSISTENCE_FAILED: 500,
        }
        return _error_response(
            status_code=status_by_code[error.code],
            code=error.code.value,
            message=str(error),
        )

    dataset = db_session.get(Dataset, result.dataset_id)
    if dataset is None:
        return _error_response(
            status_code=500,
            code=ImportServiceErrorCode.DATASET_PERSISTENCE_FAILED.value,
            message="Dataset import could not be persisted.",
        )
    return DatasetImportConfirmResponse(
        dataset_id=dataset.id,
        name=dataset.name,
        version=dataset.version,
        source=dataset.source,
        privacy_status=dataset.privacy_status,
        representativeness_statement=dataset.representativeness_statement,
        conversation_count=result.total_conversation_count,
        created_at=dataset.created_at,
    )


def _dataset_not_found(dataset_id: UUID) -> JSONResponse:
    return _error_response(
        status_code=404,
        code="dataset_not_found",
        message=f"Dataset '{dataset_id}' was not found.",
    )


def _dataset_list_item(
    dataset: Dataset,
    conversation_count: int,
) -> DatasetListItem:
    return DatasetListItem(
        dataset_id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        version=dataset.version,
        source=dataset.source,
        privacy_status=dataset.privacy_status,
        representativeness_statement=dataset.representativeness_statement,
        conversation_count=conversation_count,
        created_at=dataset.created_at,
    )


@app.get("/api/datasets", response_model=list[DatasetListItem])
def list_datasets(
    db_session: Annotated[Session, Depends(get_db_session)],
) -> list[DatasetListItem]:
    conversation_count = (
        select(func.count(Conversation.id))
        .where(Conversation.dataset_id == Dataset.id)
        .correlate(Dataset)
        .scalar_subquery()
    )
    rows = db_session.execute(
        select(Dataset, conversation_count.label("conversation_count")).order_by(
            Dataset.created_at.desc(),
            Dataset.id.desc(),
        )
    ).all()
    return [
        _dataset_list_item(dataset, count) for dataset, count in rows
    ]


@app.get(
    "/api/datasets/{dataset_id}",
    response_model=DatasetDetailResponse,
)
def get_dataset(
    dataset_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
) -> DatasetDetailResponse | JSONResponse:
    dataset = db_session.get(Dataset, dataset_id)
    if dataset is None:
        return _dataset_not_found(dataset_id)

    conversation_metadata = db_session.scalars(
        select(Conversation.metadata_).where(
            Conversation.dataset_id == dataset_id
        )
    ).all()
    scenario_distribution: dict[str, int] = {}
    for metadata in conversation_metadata:
        scenario = metadata.get("scenario") if isinstance(metadata, dict) else None
        if isinstance(scenario, str):
            scenario_distribution[scenario] = (
                scenario_distribution.get(scenario, 0) + 1
            )

    return DatasetDetailResponse(
        **_dataset_list_item(dataset, len(conversation_metadata)).model_dump(),
        scenario_distribution=dict(sorted(scenario_distribution.items())),
    )


@app.get(
    "/api/datasets/{dataset_id}/conversations",
    response_model=list[DatasetConversationRead],
)
def list_dataset_conversations(
    dataset_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
) -> list[Conversation] | JSONResponse:
    if db_session.get(Dataset, dataset_id) is None:
        return _dataset_not_found(dataset_id)

    return list(
        db_session.scalars(
            select(Conversation)
            .where(Conversation.dataset_id == dataset_id)
            .order_by(
                Conversation.external_id.asc(),
                Conversation.created_at.asc(),
                Conversation.id.asc(),
            )
        ).all()
    )
