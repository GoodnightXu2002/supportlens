from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
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
from app.models import Dataset
from app.schemas import DatasetImportConfirmRequest, DatasetImportConfirmResponse

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
