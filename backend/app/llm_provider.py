from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

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
    request_id: str | None = None
    raw_response: Any | None = None


class LLMProviderErrorCode(StrEnum):
    AUTHENTICATION_CONFIG_ERROR = "authentication_config_error"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    PROVIDER_HTTP_ERROR = "provider_http_error"
    MALFORMED_RESPONSE = "malformed_response"


class LLMProviderError(RuntimeError):
    def __init__(self, code: LLMProviderErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class DeepSeekProvider:
    provider_name = "deepseek"

    def __init__(self, settings: Settings) -> None:
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
        self.base_url = settings.deepseek_base_url
        self.model = settings.deepseek_model

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError(
            "DeepSeek transport is intentionally not implemented in 07-04-02A."
        )
