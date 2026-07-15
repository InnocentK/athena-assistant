"""
providers/chatgpt_cli.py — ChatGPT CLI adapter STUB

STATUS: Not implemented. Stub only.

WHAT THIS WOULD DO:
  ChatGPT CLI is a potential fallback when the OpenAI API is unavailable
  or undesirable. When auth details and the CLI interface are confirmed,
  implement complete() here.

HOW TO ACTIVATE:
  1. Confirm the ChatGPT CLI command name and auth method.
  2. Implement is_available() (shutil.which check) and complete() (subprocess).
  3. Set chatgpt_cli.enabled: true in config/providers.yaml.
  4. Add required env vars to .env.example.

IMPLEMENTATION NOTES:
  - Likely follows the same subprocess/prompt-formatting pattern as ClaudeAdapter.
  - Auth may require a token env var or a logged-in session file.
  - The CLI command name is not yet confirmed — placeholder is "chatgpt".
"""

from providers.base import Message, ProviderAdapter, ProviderResponse


class ChatGPTCLIAdapter(ProviderAdapter):
    """Stub adapter for a future ChatGPT CLI integration."""

    def name(self) -> str:
        return "chatgpt_cli"

    def cost_tier(self) -> str:
        return "medium"

    def is_available(self) -> bool:
        return False

    def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            success=False,
            content="",
            provider_name="chatgpt_cli",
            error=(
                "ChatGPT CLI adapter is a stub. "
                "See providers/chatgpt_cli.py for implementation notes."
            ),
        )
