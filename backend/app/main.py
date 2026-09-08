import json
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.baseline_runner import (
    BaselineRunner,
    BaselineRunnerError,
    BaselineRunnerErrorCode,
)
from app.candidate_validation import (
    CandidateComparisonService,
    CandidateRunner,
    CandidateRunService,
    CandidateValidationError,
    CandidateValidationErrorCode,
)
from app.config import get_settings
from app.database import SessionLocal
from app.human_review import (
    HumanReviewError,
    HumanReviewErrorCode,
    HumanReviewService,
)
from app.import_service import (
    ImportFileValidationError,
    ImportPreviewResult,
    ImportService,
    ImportServiceError,
    ImportServiceErrorCode,
)
from app.judge_contract import JUDGE_CONTRACT_VERSION
from app.llm_provider import DeepSeekProvider
from app.models import Conversation, Dataset, EvaluationRun, HumanDecision
from app.optimization_target import (
    OptimizationTargetError,
    OptimizationTargetErrorCode,
    OptimizationTargetService,
)
from app.problem_aggregation import (
    ProblemAggregationError,
    ProblemAggregationErrorCode,
    ProblemAggregationService,
)
from app.schemas import (
    CandidateFinalDecisionRequest,
    CandidateRunCreateRequest,
    CandidateValidationSummaryRead,
    CaseComparisonRead,
    DatasetConversationRead,
    DatasetDetailResponse,
    DatasetImportConfirmRequest,
    DatasetImportConfirmResponse,
    DatasetListItem,
    EvaluationRunCreateRequest,
    EvaluationRunRead,
    EvaluationRunSource,
    EvaluationRunStatus,
    FinalEffectiveResultRead,
    HumanDecisionRead,
    HumanReviewSubmitRequest,
    OptimizationTargetActorRequest,
    OptimizationTargetCompleteRequest,
    OptimizationTargetCreateRequest,
    OptimizationTargetPatchRequest,
    OptimizationTargetProblemSetCompleteRequest,
    OptimizationTargetProblemSetCreateRequest,
    OptimizationTargetRead,
    ProblemRead,
    ValidationTaskCasesResponse,
    ValidationTaskCreateResponse,
    ValidationTaskSubmitRequest,
    ValidationTaskSubmitResponse,
)
from app.validation_task import (
    ValidationTaskError,
    ValidationTaskErrorCode,
    ValidationTaskService,
)

settings = get_settings()

BASELINE_JUDGE_MODEL = settings.deepseek_model or "unconfigured"
BASELINE_JUDGE_CONTRACT_VERSION = JUDGE_CONTRACT_VERSION

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


@lru_cache
def get_human_review_service() -> HumanReviewService:
    return HumanReviewService()


@lru_cache
def get_problem_aggregation_service() -> ProblemAggregationService:
    return ProblemAggregationService()


@lru_cache
def get_optimization_target_service() -> OptimizationTargetService:
    return OptimizationTargetService()


@lru_cache
def get_validation_task_service() -> ValidationTaskService:
    return ValidationTaskService()


@lru_cache
def get_candidate_run_service() -> CandidateRunService:
    return CandidateRunService()


@lru_cache
def get_candidate_comparison_service() -> CandidateComparisonService:
    return CandidateComparisonService()


def get_candidate_runner() -> CandidateRunner:
    return CandidateRunner(DeepSeekProvider(settings))


def get_baseline_runner() -> BaselineRunner:
    return BaselineRunner(DeepSeekProvider(settings))


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


def _evaluation_run_not_found(run_id: UUID) -> JSONResponse:
    return _error_response(
        status_code=404,
        code="evaluation_run_not_found",
        message=f"Evaluation run '{run_id}' was not found.",
    )


def _human_review_error_response(error: HumanReviewError) -> JSONResponse:
    status_by_code = {
        HumanReviewErrorCode.EVALUATION_RESULT_NOT_FOUND: 404,
        HumanReviewErrorCode.EVALUATION_RUN_NOT_FOUND: 404,
        HumanReviewErrorCode.HUMAN_REVIEW_NOT_REQUIRED: 409,
        HumanReviewErrorCode.HUMAN_REVIEW_ALREADY_COMPLETED: 409,
        HumanReviewErrorCode.HUMAN_REVIEW_FINAL_RESULT_REQUIRED: 400,
        HumanReviewErrorCode.HUMAN_REVIEW_CONFIRM_RESULT_MISMATCH: 400,
        HumanReviewErrorCode.HUMAN_REVIEW_CHANGE_REASON_REQUIRED: 400,
        HumanReviewErrorCode.HUMAN_REVIEW_INVALID_RESULT: 400,
        HumanReviewErrorCode.HUMAN_REVIEW_PERSISTENCE_FAILED: 500,
    }
    return _error_response(
        status_code=status_by_code[error.code],
        code=error.code.value,
        message=str(error),
    )


def _problem_aggregation_error_response(
    error: ProblemAggregationError,
) -> JSONResponse:
    status_by_code = {
        ProblemAggregationErrorCode.EVALUATION_RUN_NOT_FOUND: 404,
        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_NOT_BASELINE: 409,
        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_RUN_NOT_COMPLETED: 409,
        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_FINAL_RESULTS_INCOMPLETE: 409,
        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_PENDING_REVIEW: 409,
        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_ALREADY_COMPLETED: 409,
        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_INVALID_INPUT: 400,
        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_PERSISTENCE_FAILED: 500,
    }
    return _error_response(
        status_code=status_by_code[error.code],
        code=error.code.value,
        message=str(error),
    )


def _optimization_target_error_response(
    error: OptimizationTargetError,
) -> JSONResponse:
    status_by_code = {
        OptimizationTargetErrorCode.EVALUATION_RUN_NOT_FOUND: 404,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_NOT_FOUND: 404,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_NOT_FOUND: 404,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_RUN_NOT_BASELINE: 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_RUN_NOT_COMPLETED: 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_RUN_MISMATCH: 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PENDING_REVIEW: 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_AGGREGATION_NOT_COMPLETED: 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_ALREADY_EXISTS: 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_FROZEN: 409,
        (
            OptimizationTargetErrorCode
            .OPTIMIZATION_TARGET_TARGET_CONFIRMATION_INCOMPLETE
        ): 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_TARGET_NOT_CONFIRMED: 409,
        (
            OptimizationTargetErrorCode
            .OPTIMIZATION_TARGET_HYPOTHESIS_CONFIRMATION_INCOMPLETE
        ): 409,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_FREEZE_GATE_FAILED: 409,
        (
            OptimizationTargetErrorCode
            .OPTIMIZATION_TARGET_PROBLEM_HAS_NO_AFFECTED_CASES
        ): 400,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_FAILURE_MODE_NOT_UNIQUE: 400,
        OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PERSISTENCE_FAILED: 500,
    }
    return _error_response(
        status_code=status_by_code[error.code],
        code=error.code.value,
        message=str(error),
    )


def _validation_task_error_response(error: ValidationTaskError) -> JSONResponse:
    status_by_code = {
        ValidationTaskErrorCode.OPTIMIZATION_TARGET_NOT_FOUND: 404,
        ValidationTaskErrorCode.VALIDATION_TASK_NOT_FOUND: 404,
        ValidationTaskErrorCode.RUNNER_TOKEN_INVALID: 401,
        ValidationTaskErrorCode.RUNNER_TOKEN_EXPIRED: 401,
        ValidationTaskErrorCode.VALIDATION_TASK_TARGET_NOT_FROZEN: 409,
        ValidationTaskErrorCode.VALIDATION_TASK_CASE_SCOPE_INVALID: 409,
        ValidationTaskErrorCode.VALIDATION_TASK_NOT_RUNNABLE: 409,
        ValidationTaskErrorCode.VALIDATION_TASK_NOT_SUBMITTABLE: 409,
        ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_DUPLICATE: 400,
        ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_UNKNOWN: 400,
        ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_MISSING: 400,
        ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_EMPTY: 400,
        ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED: 500,
    }
    return _error_response(
        status_code=status_by_code[error.code],
        code=error.code.value,
        message=str(error),
    )


def _candidate_validation_error_response(
    error: CandidateValidationError,
) -> JSONResponse:
    status_by_code = {
        CandidateValidationErrorCode.EVALUATION_RUN_NOT_FOUND: 404,
        CandidateValidationErrorCode.CANDIDATE_RUN_NOT_CANDIDATE: 409,
        CandidateValidationErrorCode.CANDIDATE_RUN_NOT_STARTABLE: 409,
        CandidateValidationErrorCode.CANDIDATE_BASELINE_INVALID: 409,
        CandidateValidationErrorCode.CANDIDATE_TARGET_NOT_FROZEN: 409,
        CandidateValidationErrorCode.CANDIDATE_PLAN_HASH_MISMATCH: 409,
        CandidateValidationErrorCode.CANDIDATE_EXPOSURE_BEFORE_FREEZE: 409,
        CandidateValidationErrorCode.CANDIDATE_CASE_SCOPE_INVALID: 400,
        CandidateValidationErrorCode.CANDIDATE_RESPONSE_PAIR_INVALID: 400,
        CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY: 409,
        CandidateValidationErrorCode.CANDIDATE_COMPARISON_PERSISTENCE_FAILED: 500,
        CandidateValidationErrorCode.CANDIDATE_VALIDATION_SUMMARY_NOT_FOUND: 404,
        CandidateValidationErrorCode.CANDIDATE_FINAL_DECISION_ALREADY_COMPLETED: 409,
        CandidateValidationErrorCode.CANDIDATE_FINAL_DECISION_ACCEPT_BLOCKED: 409,
        (
            CandidateValidationErrorCode
            .CANDIDATE_FINAL_DECISION_OVERRIDE_REASON_REQUIRED
        ): 409,
    }
    return _error_response(
        status_code=status_by_code[error.code],
        code=error.code.value,
        message=str(error),
    )


def _baseline_runner_error_response(error: BaselineRunnerError) -> JSONResponse:
    return _error_response(
        status_code=(
            404
            if error.code is BaselineRunnerErrorCode.EVALUATION_RUN_NOT_FOUND
            else 409
        ),
        code=error.code.value,
        message=str(error),
    )


def _dataset_business_reference_snapshot(
    dataset_id: UUID,
    db_session: Session,
) -> str:
    references = []
    for metadata in db_session.scalars(
        select(Conversation.metadata_)
        .where(Conversation.dataset_id == dataset_id)
        .order_by(Conversation.external_id, Conversation.id)
    ):
        if (
            isinstance(metadata, dict)
            and metadata.get("reference_evidence") is not None
        ):
            references.append(metadata["reference_evidence"])
    return json.dumps({"reference_evidence": references}, ensure_ascii=False)


@app.post(
    "/api/evaluation-runs",
    response_model=EvaluationRunRead,
    status_code=201,
)
def create_evaluation_run(
    request: EvaluationRunCreateRequest | CandidateRunCreateRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    candidate_service: Annotated[
        CandidateRunService,
        Depends(get_candidate_run_service),
    ],
) -> EvaluationRun | JSONResponse:
    if isinstance(request, CandidateRunCreateRequest):
        try:
            return candidate_service.create(request, db_session)
        except CandidateValidationError as error:
            return _candidate_validation_error_response(error)

    if db_session.get(Dataset, request.dataset_id) is None:
        return _dataset_not_found(request.dataset_id)

    evaluation_run = EvaluationRun(
        dataset_id=request.dataset_id,
        run_type=request.run_type.value,
        status=EvaluationRunStatus.PENDING.value,
        baseline_run_id=None,
        target_id=None,
        candidate_label=None,
        candidate_change_summary=None,
        judge_model=BASELINE_JUDGE_MODEL,
        judge_contract_version=BASELINE_JUDGE_CONTRACT_VERSION,
        run_source=EvaluationRunSource.LIVE.value,
        response_set_key=f"dataset:{request.dataset_id}:conversations",
        error_code=None,
        error_message=None,
        business_reference_snapshot=_dataset_business_reference_snapshot(
            request.dataset_id,
            db_session,
        ),
    )
    try:
        db_session.add(evaluation_run)
        db_session.commit()
    except Exception:
        db_session.rollback()
        return _error_response(
            status_code=500,
            code="evaluation_run_creation_failed",
            message="Evaluation run could not be created.",
        )
    return evaluation_run


@app.post(
    "/api/evaluation-runs/{run_id}/execute-baseline",
    response_model=EvaluationRunRead,
)
def execute_baseline_evaluation_run(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    runner: Annotated[BaselineRunner, Depends(get_baseline_runner)],
) -> EvaluationRun | JSONResponse:
    try:
        return runner.execute(run_id, db_session)
    except BaselineRunnerError as error:
        return _baseline_runner_error_response(error)


@app.get(
    "/api/evaluation-runs/{run_id}",
    response_model=EvaluationRunRead,
)
def get_evaluation_run(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
) -> EvaluationRun | JSONResponse:
    evaluation_run = db_session.get(EvaluationRun, run_id)
    if evaluation_run is None:
        return _evaluation_run_not_found(run_id)
    return evaluation_run


@app.post(
    "/api/evaluation-runs/{run_id}/execute-candidate",
    response_model=EvaluationRunRead,
)
def execute_candidate_evaluation_run(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    runner: Annotated[CandidateRunner, Depends(get_candidate_runner)],
) -> EvaluationRun | JSONResponse:
    try:
        return runner.execute(run_id, db_session)
    except CandidateValidationError as error:
        return _candidate_validation_error_response(error)


@app.post(
    "/api/evaluation-runs/{run_id}/case-comparisons",
    response_model=list[CaseComparisonRead],
    status_code=201,
)
def generate_candidate_case_comparisons(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        CandidateComparisonService,
        Depends(get_candidate_comparison_service),
    ],
) -> list[CaseComparisonRead] | JSONResponse:
    try:
        comparisons, _summary = service.generate(run_id, db_session)
        return comparisons
    except CandidateValidationError as error:
        return _candidate_validation_error_response(error)


@app.get(
    "/api/evaluation-runs/{run_id}/case-comparisons",
    response_model=list[CaseComparisonRead],
)
def list_candidate_case_comparisons(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        CandidateComparisonService,
        Depends(get_candidate_comparison_service),
    ],
) -> list[CaseComparisonRead] | JSONResponse:
    try:
        return service.list(run_id, db_session)
    except CandidateValidationError as error:
        return _candidate_validation_error_response(error)


@app.get(
    "/api/evaluation-runs/{run_id}/candidate-validation-summary",
    response_model=CandidateValidationSummaryRead,
)
def get_candidate_validation_summary(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        CandidateComparisonService,
        Depends(get_candidate_comparison_service),
    ],
) -> CandidateValidationSummaryRead | JSONResponse:
    try:
        return service.get_summary(run_id, db_session)
    except CandidateValidationError as error:
        return _candidate_validation_error_response(error)


@app.post(
    "/api/evaluation-runs/{run_id}/final-decision",
    response_model=EvaluationRunRead,
)
def submit_candidate_final_decision(
    run_id: UUID,
    request: CandidateFinalDecisionRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        CandidateComparisonService,
        Depends(get_candidate_comparison_service),
    ],
) -> EvaluationRun | JSONResponse:
    try:
        return service.submit_final_decision(run_id, request, db_session)
    except CandidateValidationError as error:
        return _candidate_validation_error_response(error)


@app.post(
    "/api/evaluation-results/{evaluation_result_id}/human-review",
    response_model=HumanDecisionRead,
    status_code=201,
)
def submit_human_review(
    evaluation_result_id: UUID,
    request: HumanReviewSubmitRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[HumanReviewService, Depends(get_human_review_service)],
) -> HumanDecision | JSONResponse:
    try:
        return service.submit(
            evaluation_result_id,
            reviewer=request.reviewer,
            action=request.action,
            final_result=request.final_result,
            change_reason=request.change_reason,
            db_session=db_session,
        )
    except HumanReviewError as error:
        return _human_review_error_response(error)


@app.get(
    "/api/evaluation-runs/{run_id}/final-effective-results",
    response_model=list[FinalEffectiveResultRead],
)
def list_final_effective_results(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[HumanReviewService, Depends(get_human_review_service)],
) -> list[FinalEffectiveResultRead] | JSONResponse:
    try:
        return service.list_final_effective_results(run_id, db_session)
    except HumanReviewError as error:
        return _human_review_error_response(error)


@app.post(
    "/api/evaluation-runs/{run_id}/problems",
    response_model=list[ProblemRead],
    status_code=201,
)
def generate_problems(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        ProblemAggregationService,
        Depends(get_problem_aggregation_service),
    ],
) -> list[ProblemRead] | JSONResponse:
    try:
        return service.generate(run_id, db_session)
    except ProblemAggregationError as error:
        return _problem_aggregation_error_response(error)


@app.get(
    "/api/evaluation-runs/{run_id}/problems",
    response_model=list[ProblemRead],
)
def list_problems(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        ProblemAggregationService,
        Depends(get_problem_aggregation_service),
    ],
) -> list[ProblemRead] | JSONResponse:
    try:
        return service.list_problems(run_id, db_session)
    except ProblemAggregationError as error:
        return _problem_aggregation_error_response(error)


@app.post(
    "/api/evaluation-runs/{run_id}/problems/{problem_id}/optimization-targets",
    response_model=OptimizationTargetRead,
    status_code=201,
)
def create_optimization_target(
    run_id: UUID,
    problem_id: UUID,
    request: OptimizationTargetCreateRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.create(run_id, problem_id, request, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.post(
    "/api/evaluation-runs/{run_id}/problems/{problem_id}/optimization-targets/complete",
    response_model=OptimizationTargetRead,
)
def complete_optimization_target(
    run_id: UUID,
    problem_id: UUID,
    request: OptimizationTargetCompleteRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.complete(run_id, problem_id, request, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.post(
    "/api/evaluation-runs/{run_id}/optimization-targets",
    response_model=OptimizationTargetRead,
    status_code=201,
)
def create_problem_set_optimization_target(
    run_id: UUID,
    request: OptimizationTargetProblemSetCreateRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        target = OptimizationTargetCreateRequest.model_validate(
            request.model_dump(exclude={"problem_ids"})
        )
        return service.create_for_problems(
            run_id, request.problem_ids, target, db_session
        )
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.post(
    "/api/evaluation-runs/{run_id}/optimization-targets/complete",
    response_model=OptimizationTargetRead,
)
def complete_problem_set_optimization_target(
    run_id: UUID,
    request: OptimizationTargetProblemSetCompleteRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.complete_for_problems(
            run_id, request.problem_ids, request.target, request.actor, db_session
        )
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.get(
    "/api/optimization-targets/{target_id}",
    response_model=OptimizationTargetRead,
)
def get_optimization_target(
    target_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.get(target_id, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.patch(
    "/api/optimization-targets/{target_id}",
    response_model=OptimizationTargetRead,
)
def patch_optimization_target(
    target_id: UUID,
    request: OptimizationTargetPatchRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.patch(target_id, request, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.post(
    "/api/optimization-targets/{target_id}/confirm-target",
    response_model=OptimizationTargetRead,
)
def confirm_optimization_target(
    target_id: UUID,
    request: OptimizationTargetActorRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.confirm_target(target_id, request, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.post(
    "/api/optimization-targets/{target_id}/confirm-hypothesis",
    response_model=OptimizationTargetRead,
)
def confirm_optimization_target_hypothesis(
    target_id: UUID,
    request: OptimizationTargetActorRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.confirm_hypothesis(target_id, request, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.post(
    "/api/optimization-targets/{target_id}/freeze",
    response_model=OptimizationTargetRead,
)
def freeze_optimization_target(
    target_id: UUID,
    request: OptimizationTargetActorRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> OptimizationTargetRead | JSONResponse:
    try:
        return service.freeze(target_id, request, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.get(
    "/api/evaluation-runs/{run_id}/optimization-targets",
    response_model=list[OptimizationTargetRead],
)
def list_optimization_targets(
    run_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        OptimizationTargetService,
        Depends(get_optimization_target_service),
    ],
) -> list[OptimizationTargetRead] | JSONResponse:
    try:
        return service.list_for_run(run_id, db_session)
    except OptimizationTargetError as error:
        return _optimization_target_error_response(error)


@app.post(
    "/api/optimization-targets/{target_id}/validation-tasks",
    response_model=ValidationTaskCreateResponse,
    status_code=201,
)
def create_validation_task(
    target_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        ValidationTaskService,
        Depends(get_validation_task_service),
    ],
) -> ValidationTaskCreateResponse | JSONResponse:
    try:
        return service.create(target_id, db_session)
    except ValidationTaskError as error:
        return _validation_task_error_response(error)


@app.get(
    "/api/validation-tasks/{task_id}/cases",
    response_model=ValidationTaskCasesResponse,
)
def get_validation_task_cases(
    task_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        ValidationTaskService,
        Depends(get_validation_task_service),
    ],
    authorization: Annotated[str | None, Header()] = None,
) -> ValidationTaskCasesResponse | JSONResponse:
    try:
        return service.get_cases(task_id, authorization, db_session)
    except ValidationTaskError as error:
        return _validation_task_error_response(error)


@app.post(
    "/api/validation-tasks/{task_id}/responses",
    response_model=ValidationTaskSubmitResponse,
)
def submit_validation_task_responses(
    task_id: UUID,
    request: ValidationTaskSubmitRequest,
    db_session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        ValidationTaskService,
        Depends(get_validation_task_service),
    ],
    authorization: Annotated[str | None, Header()] = None,
) -> ValidationTaskSubmitResponse | JSONResponse:
    try:
        return service.submit(task_id, authorization, request, db_session)
    except ValidationTaskError as error:
        return _validation_task_error_response(error)


@app.get(
    "/api/datasets/{dataset_id}/evaluation-runs",
    response_model=list[EvaluationRunRead],
)
def list_dataset_evaluation_runs(
    dataset_id: UUID,
    db_session: Annotated[Session, Depends(get_db_session)],
) -> list[EvaluationRun] | JSONResponse:
    if db_session.get(Dataset, dataset_id) is None:
        return _dataset_not_found(dataset_id)

    return list(
        db_session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.dataset_id == dataset_id)
            .order_by(
                EvaluationRun.created_at.desc(),
                EvaluationRun.id.desc(),
            )
        ).all()
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
