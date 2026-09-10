from __future__ import annotations

import json
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.llm_provider import (
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    ProviderMessage,
    ProviderMessageRole,
)
from app.models import OptimizationTarget, Problem
from app.schemas import (
    OptimizationSuggestionRead,
    OptimizationTargetStatus,
    OptimizationTargetSuggestionsRead,
)

OPTIMIZATION_SUGGESTION_PROMPT_VERSION = "OPTIMIZATION-SUGGESTION-PROMPT-V1"


class _SuggestionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_id: str
    suggestion: str


class _SuggestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: list[_SuggestionItem]


class OptimizationSuggestionsErrorCode(StrEnum):
    OPTIMIZATION_TARGET_NOT_FOUND = "optimization_target_not_found"
    OPTIMIZATION_SUGGESTIONS_TARGET_FROZEN = (
        "optimization_suggestions_target_frozen"
    )
    OPTIMIZATION_SUGGESTIONS_PROBLEM_NOT_FOUND = (
        "optimization_suggestions_problem_not_found"
    )
    OPTIMIZATION_SUGGESTIONS_LLM_FAILED = "optimization_suggestions_llm_failed"
    OPTIMIZATION_SUGGESTIONS_LLM_OUTPUT_INVALID = (
        "optimization_suggestions_llm_output_invalid"
    )
    OPTIMIZATION_SUGGESTIONS_PERSISTENCE_FAILED = (
        "optimization_suggestions_persistence_failed"
    )


class OptimizationSuggestionsError(RuntimeError):
    def __init__(
        self,
        code: OptimizationSuggestionsErrorCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


class OptimizationSuggestionsService:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def generate(
        self,
        target_id: UUID,
        db_session: Session,
        *,
        commit: bool = True,
    ) -> OptimizationTargetSuggestionsRead:
        target = db_session.get(OptimizationTarget, target_id)
        if target is None:
            raise OptimizationSuggestionsError(
                OptimizationSuggestionsErrorCode.OPTIMIZATION_TARGET_NOT_FOUND,
                f"Optimization target '{target_id}' was not found.",
            )

        stored = _stored_suggestions(target.optimization_suggestions)
        if stored is not None:
            return OptimizationTargetSuggestionsRead(
                optimization_target_id=target.id,
                generated=False,
                suggestions=stored,
            )
        if target.status == OptimizationTargetStatus.FROZEN.value:
            raise OptimizationSuggestionsError(
                (
                    OptimizationSuggestionsErrorCode
                    .OPTIMIZATION_SUGGESTIONS_TARGET_FROZEN
                ),
                "Frozen optimization targets cannot generate suggestions.",
            )

        problems = self._load_problems(target, db_session)
        try:
            response = self._provider.complete(
                _assemble_suggestion_request(problems)
            )
        except LLMProviderError as error:
            raise OptimizationSuggestionsError(
                OptimizationSuggestionsErrorCode.OPTIMIZATION_SUGGESTIONS_LLM_FAILED,
                "Optimization suggestions could not be generated.",
            ) from error
        suggestions = _validate_suggestion_output(
            response.structured_payload,
            problems,
        )

        target.optimization_suggestions = [
            suggestion.model_dump(mode="json") for suggestion in suggestions
        ]
        try:
            if commit:
                db_session.commit()
            else:
                db_session.flush()
        except SQLAlchemyError as error:
            db_session.rollback()
            raise OptimizationSuggestionsError(
                (
                    OptimizationSuggestionsErrorCode
                    .OPTIMIZATION_SUGGESTIONS_PERSISTENCE_FAILED
                ),
                "Optimization suggestions could not be persisted.",
            ) from error
        return OptimizationTargetSuggestionsRead(
            optimization_target_id=target.id,
            generated=True,
            suggestions=suggestions,
        )

    def _load_problems(
        self,
        target: OptimizationTarget,
        db_session: Session,
    ) -> list[Problem]:
        raw_problem_ids = target.problem_ids or [str(target.problem_id)]
        problems: list[Problem] = []
        seen: set[UUID] = set()
        for raw_problem_id in raw_problem_ids:
            problem_id = UUID(raw_problem_id)
            if problem_id in seen:
                continue
            seen.add(problem_id)
            problem = db_session.get(Problem, problem_id)
            if problem is None or problem.evaluation_run_id != target.baseline_run_id:
                raise OptimizationSuggestionsError(
                    (
                        OptimizationSuggestionsErrorCode
                        .OPTIMIZATION_SUGGESTIONS_PROBLEM_NOT_FOUND
                    ),
                    f"Problem '{problem_id}' was not found for this target.",
                )
            problems.append(problem)
        return problems


def _stored_suggestions(
    value: Any,
) -> list[OptimizationSuggestionRead] | None:
    if not isinstance(value, list) or not value:
        return None
    try:
        suggestions = [
            OptimizationSuggestionRead.model_validate(item) for item in value
        ]
    except ValidationError:
        return None
    return suggestions


def _validate_suggestion_output(
    payload: dict[str, Any],
    problems: list[Problem],
) -> list[OptimizationSuggestionRead]:
    try:
        output = _SuggestionOutput.model_validate(payload)
    except ValidationError as error:
        raise OptimizationSuggestionsError(
            (
                OptimizationSuggestionsErrorCode
                .OPTIMIZATION_SUGGESTIONS_LLM_OUTPUT_INVALID
            ),
            "Suggestion output did not match the expected schema.",
        ) from error

    suggestion_by_problem_id: dict[UUID, str] = {}
    for item in output.suggestions:
        try:
            problem_id = UUID(item.problem_id)
        except ValueError as error:
            raise OptimizationSuggestionsError(
                (
                    OptimizationSuggestionsErrorCode
                    .OPTIMIZATION_SUGGESTIONS_LLM_OUTPUT_INVALID
                ),
                "Suggestion output contained an invalid problem_id.",
            ) from error
        suggestion = item.suggestion.strip()
        if not suggestion or problem_id in suggestion_by_problem_id:
            raise OptimizationSuggestionsError(
                (
                    OptimizationSuggestionsErrorCode
                    .OPTIMIZATION_SUGGESTIONS_LLM_OUTPUT_INVALID
                ),
                "Suggestion output must contain one suggestion per problem.",
            )
        suggestion_by_problem_id[problem_id] = suggestion

    expected_problem_ids = {problem.id for problem in problems}
    if set(suggestion_by_problem_id) != expected_problem_ids:
        raise OptimizationSuggestionsError(
            (
                OptimizationSuggestionsErrorCode
                .OPTIMIZATION_SUGGESTIONS_LLM_OUTPUT_INVALID
            ),
            "Suggestion output must match the requested problems exactly.",
        )
    return [
        OptimizationSuggestionRead(
            problem_id=problem.id,
            suggestion=suggestion_by_problem_id[problem.id],
        )
        for problem in problems
    ]


def _assemble_suggestion_request(problems: list[Problem]) -> LLMRequest:
    system_prompt = "\n".join(
        [
            "Generate one support-system optimization suggestion for each "
            "problem listed in the user payload.",
            "Return only structured JSON matching the supplied response "
            "schema.",
            "Return exactly one suggestion object per listed problem. Copy "
            "each problem_id value unchanged; do not add, drop, merge, or "
            "duplicate problems.",
            "Write every suggestion in Simplified Chinese.",
            "Each suggestion must describe only an improvement direction for "
            "how the support assistant should behave: its customer-service "
            "actions, answer strategy, or use of conversation context, "
            "addressing that problem's scenario and definition.",
            "Do not mention prompt line numbers, knowledge base files, or "
            "named agent or system configuration items.",
            "Do not provide chain-of-thought. Keep each suggestion concise "
            "and specific to its problem.",
        ]
    )
    user_payload = {
        "problems": [
            {
                "problem_id": str(problem.id),
                "scenario": problem.scenario,
                "definition": problem.definition,
            }
            for problem in problems
        ],
        "suggestion_output_schema": _SuggestionOutput.model_json_schema(),
    }
    return LLMRequest(
        messages=[
            ProviderMessage(
                role=ProviderMessageRole.SYSTEM,
                content=system_prompt,
            ),
            ProviderMessage(
                role=ProviderMessageRole.USER,
                content=json.dumps(user_payload, ensure_ascii=False),
            ),
        ],
        response_schema_name="OptimizationSuggestions",
        response_schema=_SuggestionOutput.model_json_schema(),
        metadata={
            "suggestion_prompt_version": OPTIMIZATION_SUGGESTION_PROMPT_VERSION,
        },
    )
