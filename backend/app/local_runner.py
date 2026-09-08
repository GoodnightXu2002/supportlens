from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

REQUEST_TIMEOUT_SECONDS = 30.0
REQUIRED_ENVIRONMENT = (
    "SUPPORTLENS_BASE_URL",
    "RUNNER_TASK_ID",
    "RUNNER_TOKEN",
    "AGENT_ENDPOINT",
    "AGENT_API_KEY",
    "AGENT_MODEL",
)


class LocalRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunnerConfig:
    supportlens_base_url: str
    task_id: UUID
    runner_token: str = field(repr=False)
    agent_endpoint: str
    agent_api_key: str = field(repr=False)
    agent_model: str

    @classmethod
    def from_environment(cls) -> RunnerConfig:
        values = {
            name: os.environ.get(name, "").strip()
            for name in REQUIRED_ENVIRONMENT
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise LocalRunnerError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        try:
            task_id = UUID(values["RUNNER_TASK_ID"])
        except ValueError as error:
            raise LocalRunnerError("RUNNER_TASK_ID must be a valid UUID.") from error
        return cls(
            supportlens_base_url=values["SUPPORTLENS_BASE_URL"].rstrip("/"),
            task_id=task_id,
            runner_token=values["RUNNER_TOKEN"],
            agent_endpoint=values["AGENT_ENDPOINT"].rstrip("/"),
            agent_api_key=values["AGENT_API_KEY"],
            agent_model=values["AGENT_MODEL"],
        )

    @property
    def chat_completions_url(self) -> str:
        if self.agent_endpoint.endswith("/chat/completions"):
            return self.agent_endpoint
        return f"{self.agent_endpoint}/chat/completions"


def run_validation_task(config: RunnerConfig, client: httpx.Client) -> int:
    task_path = quote(str(config.task_id), safe="")
    support_headers = {"Authorization": f"Bearer {config.runner_token}"}
    try:
        task_response = client.get(
            f"{config.supportlens_base_url}/api/validation-tasks/{task_path}/cases",
            headers=support_headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as error:
        raise LocalRunnerError("SupportLens task request timed out.") from error
    except httpx.TransportError as error:
        raise LocalRunnerError("SupportLens task request failed.") from error
    if task_response.is_error:
        raise LocalRunnerError(_supportlens_error(task_response))

    cases = _extract_cases(task_response)
    candidate_responses = [
        {
            "case_id": case_id,
            "assistant_content": _complete_case(
                config,
                client,
                case_id=case_id,
                messages=messages,
            ),
        }
        for case_id, messages in cases
    ]

    try:
        submit_response = client.post(
            f"{config.supportlens_base_url}/api/validation-tasks/"
            f"{task_path}/responses",
            headers=support_headers,
            json={"responses": candidate_responses},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as error:
        raise LocalRunnerError("SupportLens response submission timed out.") from error
    except httpx.TransportError as error:
        raise LocalRunnerError("SupportLens response submission failed.") from error
    if submit_response.is_error:
        raise LocalRunnerError(_supportlens_error(submit_response))
    return len(candidate_responses)


def _extract_cases(response: httpx.Response) -> list[tuple[str, list[dict[str, Any]]]]:
    try:
        payload = response.json()
    except ValueError as error:
        raise LocalRunnerError("SupportLens returned malformed task data.") from error
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise LocalRunnerError("SupportLens task did not contain frozen cases.")

    extracted: list[tuple[str, list[dict[str, Any]]]] = []
    for item in cases:
        case_id = item.get("case_id") if isinstance(item, dict) else None
        messages = item.get("messages") if isinstance(item, dict) else None
        if (
            not isinstance(case_id, str)
            or not case_id
            or not isinstance(messages, list)
        ):
            raise LocalRunnerError("SupportLens returned an invalid frozen case.")
        if not all(isinstance(message, dict) for message in messages):
            raise LocalRunnerError(f"Case {case_id}: messages are invalid.")
        extracted.append((case_id, messages))
    return extracted


def _complete_case(
    config: RunnerConfig,
    client: httpx.Client,
    *,
    case_id: str,
    messages: list[dict[str, Any]],
) -> str:
    try:
        response = client.post(
            config.chat_completions_url,
            headers={"Authorization": f"Bearer {config.agent_api_key}"},
            json={
                "model": config.agent_model,
                "messages": messages,
                "stream": False,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as error:
        raise LocalRunnerError(f"Case {case_id}: Agent request timed out.") from error
    except httpx.TransportError as error:
        raise LocalRunnerError(f"Case {case_id}: Agent request failed.") from error
    if response.status_code == 401:
        raise LocalRunnerError(
            f"Case {case_id}: Agent authentication failed (HTTP 401)."
        )
    if response.is_error:
        raise LocalRunnerError(
            f"Case {case_id}: Agent returned HTTP {response.status_code}."
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise LocalRunnerError(
            f"Case {case_id}: Agent returned malformed JSON."
        ) from error
    choices = payload.get("choices") if isinstance(payload, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise LocalRunnerError(
            f"Case {case_id}: Agent response content was empty or missing."
        )
    return content


def _supportlens_error(response: httpx.Response) -> str:
    code = None
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
    except ValueError:
        pass
    suffix = f", {code}" if isinstance(code, str) else ""
    return f"SupportLens request failed (HTTP {response.status_code}{suffix})."


def main() -> int:
    try:
        config = RunnerConfig.from_environment()
        with httpx.Client() as client:
            response_count = run_validation_task(config, client)
    except LocalRunnerError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Submitted {response_count} candidate responses for task {config.task_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
