import json
from uuid import UUID

import httpx
import pytest

from app import local_runner
from app.local_runner import LocalRunnerError, RunnerConfig, run_validation_task

TASK_ID = UUID("12345678-1234-5678-1234-567812345678")
RUNNER_TOKEN = "runner-secret"
AGENT_API_KEY = "agent-super-secret"


def _config() -> RunnerConfig:
    return RunnerConfig(
        supportlens_base_url="http://supportlens.test",
        task_id=TASK_ID,
        runner_token=RUNNER_TOKEN,
        agent_endpoint="http://agent.test/v1",
        agent_api_key=AGENT_API_KEY,
        agent_model="candidate-model",
    )


def _task_payload() -> dict[str, object]:
    return {
        "task_id": str(TASK_ID),
        "status": "running",
        "cases": [
            {
                "case_id": "CASE-A",
                "set": "target",
                "messages": [{"role": "user", "content": "Question A"}],
            },
            {
                "case_id": "CASE-B",
                "set": "regression",
                "messages": [{"role": "user", "content": "Question B"}],
            },
        ],
    }


def test_cli_runs_complete_task_and_keeps_agent_key_local(
    monkeypatch,
    capsys,
) -> None:
    captured: dict[str, object] = {"agent_requests": [], "support_headers": []}
    client_options: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "supportlens.test" and request.method == "GET":
            captured["support_headers"].append(dict(request.headers))
            return httpx.Response(200, json=_task_payload())
        if request.url.host == "agent.test":
            payload = json.loads(request.content)
            captured["agent_requests"].append(payload)
            assert request.headers["authorization"] == f"Bearer {AGENT_API_KEY}"
            content = f"Answer for {payload['messages'][0]['content']}"
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": content}}]},
            )
        if request.url.host == "supportlens.test" and request.method == "POST":
            captured["support_headers"].append(dict(request.headers))
            captured["submission"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "task_id": str(TASK_ID),
                    "status": "submitted",
                    "response_count": 2,
                    "submitted_at": "2026-09-09T00:00:00Z",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    environment = {
        "SUPPORTLENS_BASE_URL": "http://supportlens.test",
        "RUNNER_TASK_ID": str(TASK_ID),
        "RUNNER_TOKEN": RUNNER_TOKEN,
        "AGENT_ENDPOINT": "http://agent.test/v1",
        "AGENT_API_KEY": AGENT_API_KEY,
        "AGENT_MODEL": "candidate-model",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    def client_factory(**kwargs) -> httpx.Client:
        client_options.update(kwargs)
        return client

    monkeypatch.setattr(local_runner.httpx, "Client", client_factory)

    assert local_runner.main() == 0
    output = capsys.readouterr()
    assert "Submitted 2 candidate responses" in output.out
    assert output.err == ""
    assert captured["agent_requests"] == [
        {
            "model": "candidate-model",
            "messages": [{"role": "user", "content": "Question A"}],
            "stream": False,
        },
        {
            "model": "candidate-model",
            "messages": [{"role": "user", "content": "Question B"}],
            "stream": False,
        },
    ]
    assert captured["submission"] == {
        "responses": [
            {
                "case_id": "CASE-A",
                "assistant_content": "Answer for Question A",
            },
            {
                "case_id": "CASE-B",
                "assistant_content": "Answer for Question B",
            },
        ]
    }
    assert all(
        headers["authorization"] == f"Bearer {RUNNER_TOKEN}"
        for headers in captured["support_headers"]
    )
    assert AGENT_API_KEY not in output.out + output.err
    assert AGENT_API_KEY not in json.dumps(captured["submission"])
    assert AGENT_API_KEY not in repr(_config())
    assert client_options == {"trust_env": False}


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [(401, "authentication failed"), (500, "returned HTTP 500")],
)
def test_agent_http_error_names_case_and_does_not_submit(
    status_code: int,
    reason: str,
) -> None:
    submitted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted
        if request.url.host == "supportlens.test" and request.method == "GET":
            return httpx.Response(200, json=_task_payload())
        if request.url.host == "agent.test":
            return httpx.Response(status_code, json={"error": AGENT_API_KEY})
        submitted = True
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(
            LocalRunnerError,
            match=rf"Case CASE-A: Agent {reason}",
        ) as error:
            run_validation_task(_config(), client)
    assert submitted is False
    assert AGENT_API_KEY not in str(error.value)


def test_agent_timeout_names_case_and_does_not_submit() -> None:
    submitted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted
        if request.url.host == "supportlens.test" and request.method == "GET":
            return httpx.Response(200, json=_task_payload())
        if request.url.host == "agent.test":
            raise httpx.ReadTimeout("secret timeout", request=request)
        submitted = True
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(
            LocalRunnerError,
            match="Case CASE-A: Agent request timed out",
        ):
            run_validation_task(_config(), client)
    assert submitted is False


def test_supportlens_token_error_stops_before_agent_call() -> None:
    agent_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal agent_called
        if request.url.host == "supportlens.test":
            assert request.headers["authorization"] == f"Bearer {RUNNER_TOKEN}"
            return httpx.Response(
                401,
                json={"error": {"code": "runner_token_invalid"}},
            )
        agent_called = True
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(
            LocalRunnerError,
            match=r"HTTP 401, runner_token_invalid",
        ):
            run_validation_task(_config(), client)
    assert agent_called is False
