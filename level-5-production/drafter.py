"""The only file that talks to the LLM (Groq, via LangChain). Level 5 adds adraft().

Uses the `langchain_groq` module (ChatGroq). Also holds a small guardrail:
never trust LLM output blindly.
"""

import os
import re
from dataclasses import dataclass

import groq  # installed automatically as a dependency of langchain-groq
from langchain_groq import ChatGroq

from prompts import build_messages
from routing import ReplyKind

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\d[\d\s().-]{5,}\d")  # 7+ digits with common separators


class DraftError(Exception):
    """Raised when the LLM call fails or returns nothing usable."""


@dataclass(frozen=True)
class Draft:
    text: str
    warnings: tuple[str, ...]
    prompt_tokens: int
    completion_tokens: int


def check_draft(draft: str) -> tuple[str, ...]:
    """Cheap safety checks on LLM output. Returns a tuple of warnings."""
    warnings = []
    if EMAIL_RE.search(draft) or PHONE_RE.search(draft):
        warnings.append("draft contains an email or phone number")
    if len(draft) > 900:
        warnings.append("draft is longer than expected")
    if not draft.startswith("Hi"):
        warnings.append("draft does not follow the expected format")
    return tuple(warnings)


class Drafter:
    def __init__(self) -> None:
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        # ChatGroq reads GROQ_API_KEY from the environment automatically.
        self.llm = ChatGroq(
            model=self.model,
            temperature=0.3,
            # gpt-oss is a reasoning model: thinking tokens count against this
            # limit, so keep it generous and the effort low.
            max_tokens=1500,
            reasoning_effort="low",
            # Passed straight through to Groq: keep the thinking out of the reply.
            model_kwargs={"include_reasoning": False},
            timeout=60,
            max_retries=2,
        )

    def verify_model(self) -> None:
        """Fail early, with a clear message, if the model is not available.

        ChatGroq has no "list models" call, so we use the underlying groq client.
        """
        try:
            available = {m.id for m in groq.Groq().models.list().data}
        except groq.AuthenticationError:
            raise DraftError("Groq authentication failed. Check GROQ_API_KEY in .env.")
        except groq.APIError as err:
            raise DraftError(f"Could not list Groq models: {err}")
        if self.model not in available:
            raise DraftError(
                f"Model '{self.model}' is not available on your Groq account. "
                f"Set GROQ_MODEL in .env to one of: {', '.join(sorted(available))}"
            )

    def draft(self, kind: ReplyKind, post_text: str) -> Draft:
        try:
            # LangChain accepts OpenAI-style {"role", "content"} message dicts.
            message = self.llm.invoke(build_messages(kind, post_text))
        except Exception as err:
            raise self._translate(err)
        return self._to_draft(message)

    async def adraft(self, kind: ReplyKind, post_text: str) -> Draft:
        """Async version (NEW in Level 5): many drafts can be in flight at once."""
        try:
            message = await self.llm.ainvoke(build_messages(kind, post_text))
        except Exception as err:
            raise self._translate(err)
        return self._to_draft(message)

    @staticmethod
    def _translate(err: Exception) -> Exception:
        """Turn Groq errors into DraftError with a readable message."""
        if isinstance(err, groq.RateLimitError):
            return DraftError("Groq rate limit reached (after retries).")
        if isinstance(err, groq.AuthenticationError):
            return DraftError("Groq authentication failed. Check GROQ_API_KEY in .env.")
        if isinstance(err, groq.APIError):
            return DraftError(f"Groq API error: {err}")
        return err  # not a Groq error: let it surface unchanged

    @staticmethod
    def _to_draft(message) -> Draft:
        text = (message.content or "").strip()
        if not text:
            raise DraftError("The model returned an empty draft "
                             "(reasoning may have used the whole token budget).")
        usage = message.usage_metadata or {}
        return Draft(
            text=text,
            warnings=check_draft(text),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
        )
