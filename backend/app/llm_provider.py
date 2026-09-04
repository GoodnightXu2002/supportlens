from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from app.config import Settings


class _StrictProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"


class ProviderMessage(_StrictProviderModel):
    role: ProviderMessageRole
    content: str


class LLMRequest(_StrictProviderModel):
    messages: list[ProviderMessage]
    response_schema_name: str
    response_schema: dict[str, Any]
    metadata: dict[str, str]


class LLMResponse(_StrictProviderModel):
    provider: str
    model: str
    structured_payload: dict[str, Any]
    raw_json_text: str
    request_id: str | None = None
    token_usage: dict[str, int] | None = None
    raw_response: Any | None = None


class LLMProviderErrorCode(StrEnum):
    AUTHENTICATION_CONFIG_ERROR = "authentication_config_error"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    PROVIDER_HTTP_ERROR = "provider_http_error"
    MALFORMED_RESPONSE = "malformed_response"


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        code: LLMProviderErrorCode,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class DeepSeekProvider:
    provider_name = "deepseek"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if settings.deepseek_api_key is None:
            raise LLMProviderError(
                LLMProviderErrorCode.AUTHENTICATION_CONFIG_ERROR,
                "DEEPSEEK_API_KEY is required to configure DeepSeek.",
            )
        if not settings.deepseek_base_url or not settings.deepseek_model:
            raise LLMProviderError(
                LLMProviderErrorCode.AUTHENTICATION_CONFIG_ERROR,
                "DEEPSEEK_BASE_URL and DEEPSEEK_MODEL are required to configure "
                "DeepSeek.",
            )

        self._api_key: SecretStr = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client()

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [
                message.model_dump(mode="json") for message in request.messages
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": (
                f"Bearer {self._api_key.get_secret_value()}"
            ),
            "Content-Type": "application/json",
        }
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise LLMProviderError(
                LLMProviderErrorCode.TIMEOUT,
                "DeepSeek request timed out.",
                retryable=True,
            ) from error
        except httpx.TransportError as error:
            raise LLMProviderError(
                LLMProviderErrorCode.TRANSPORT_ERROR,
                "DeepSeek transport request failed.",
                retryable=True,
            ) from error

        if response.status_code == 401:
            raise LLMProviderError(
                LLMProviderErrorCode.AUTHENTICATION_CONFIG_ERROR,
                "DeepSeek authentication failed.",
                status_code=response.status_code,
            )
        if response.is_error:
            raise LLMProviderError(
                LLMProviderErrorCode.PROVIDER_HTTP_ERROR,
                "DeepSeek returned an HTTP error.",
                retryable=(
                    response.status_code == 429 or response.status_code >= 500
                ),
                status_code=response.status_code,
            )

        response_payload = self._response_json(response)
        content = self._extract_content(response_payload)
        structured_payload = self._parse_structured_payload(content)
        usage = response_payload.get("usage")
        token_usage = (
            {
                key: value
                for key, value in usage.items()
                if isinstance(key, str) and isinstance(value, int)
            }
            if isinstance(usage, dict)
            else None
        )
        request_id = response_payload.get("id")
        return LLMResponse(
            provider=self.provider_name,
            model=self.model,
            structured_payload=structured_payload,
            raw_json_text=content,
            request_id=request_id if isinstance(request_id, str) else None,
            token_usage=token_usage,
        )

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise LLMProviderError(
                LLMProviderErrorCode.MALFORMED_RESPONSE,
                "DeepSeek returned a malformed response.",
                retryable=True,
            ) from error
        if not isinstance(payload, dict):
            raise LLMProviderError(
                LLMProviderErrorCode.MALFORMED_RESPONSE,
                "DeepSeek returned a malformed response.",
                retryable=True,
            )
        return payload

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMProviderError(
                LLMProviderErrorCode.MALFORMED_RESPONSE,
                "DeepSeek response did not contain a message.",
                retryable=True,
            )
        first_choice = choices[0]
        message = (
            first_choice.get("message")
            if isinstance(first_choice, dict)
            else None
        )
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError(
                LLMProviderErrorCode.MALFORMED_RESPONSE,
                "DeepSeek response message content was empty or missing.",
                retryable=True,
            )
        return content

    @staticmethod
    def _parse_structured_payload(content: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise LLMProviderError(
                LLMProviderErrorCode.MALFORMED_RESPONSE,
                "DeepSeek response content was not valid JSON.",
                retryable=True,
            ) from error
        if not isinstance(payload, dict):
            raise LLMProviderError(
                LLMProviderErrorCode.MALFORMED_RESPONSE,
                "DeepSeek response JSON root must be an object.",
                retryable=True,
            )
        return payload
