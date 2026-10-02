from __future__ import annotations

from pathlib import Path

from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel

from app import config

PROMPTS_DIR = config.REPO_ROOT / "app" / "prompts"


class LLMService:
    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.model_id = model_id or config.BEDROCK_MODEL_ID
        self.region = region or config.BEDROCK_REGION
        self.max_tokens = max_tokens or config.BEDROCK_MAX_TOKENS
        self._chat = ChatBedrockConverse(
            model=self.model_id, region_name=self.region, max_tokens=self.max_tokens
        )

    def structured_plan(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """Returns an instance of `schema`, already Pydantic-validated by
        langchain's structured-output path. Never returns free-form text."""
        structured = self._chat.with_structured_output(schema)
        result = structured.invoke(prompt)
        return result if isinstance(result, schema) else schema.model_validate(result)


def load_prompt_template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text()
