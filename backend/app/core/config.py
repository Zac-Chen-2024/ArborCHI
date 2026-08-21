from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DeepSeek API (default provider)
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com/v1"

    # OpenAI API (alternative)
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"

    # Anthropic API (native Messages API via the official SDK)
    anthropic_api_key: str = ""
    anthropic_api_base: str = ""

    # LLM Provider: one of llm_providers.PROVIDERS (that tuple is the
    # authority; this file must not keep a second copy of the list).
    llm_provider: str = "deepseek"

    # Content-addressed LLM response cache (data/llm_cache). Dev: on; prod: off.
    llm_cache_enabled: bool = False
    # Per-call JSONL traces (data/traces/{date}.jsonl)
    llm_trace_enabled: bool = True

    # CORS allow-list, comma-separated, e.g.
    #   CORS_ORIGINS=http://localhost:5173,https://petition.example.com
    # Kept as a plain string so that pydantic-settings does not try to
    # JSON-decode the env value; use `cors_origin_list` to read it.
    cors_origins: str = "http://localhost:5173"

    # Logging level for the application logger ("DEBUG" / "INFO" / ...)
    log_level: str = "INFO"

    # Root data directory. Empty -> backend/data. Docker sets it explicitly;
    # tests point it at a temp dir.
    data_dir: str = ""

    # Root of the ORIGINAL case material (PDF/<letter>/<exhibit>.pdf ...) that
    # metadata.json.source_path points into. Empty -> <repo>/data. Docker sets
    # /app/data. Used only as a fallback when the stored absolute path is not
    # present on this machine (paths were recorded on a Windows dev box).
    source_data_dir: str = ""

    # Workspace auth. False (default): every /api request needs a bearer token
    # minted with scripts/mint_token.py. True: unauthenticated requests fall
    # back to the "default" workspace (local development).
    auth_disabled: bool = False

    # Set by the test suite; skips the fail-fast LLM key check at startup.
    skip_llm_config_check: bool = False

    # ---- Study platform ------------------------------------------------
    # Phase timing is NOT here: it lives in backend/study_config.json, whose
    # hash rides in every event so a session's actual parameters are
    # recoverable from its own log (see core/study_config.py). Only genuine
    # deployment settings belong in this file.
    # Base URL the moderator panel builds join links against.
    study_join_base_url: str = "http://localhost:5174"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def api_key_for(self, provider: str) -> str:
        # openai_responses speaks a different wire protocol (/responses rather
        # than /chat/completions) but authenticates with the same key, so it
        # deliberately shares openai_api_key rather than adding a second one
        # nobody would remember to fill in.
        return {"deepseek": self.deepseek_api_key, "openai": self.openai_api_key,
                "openai_responses": self.openai_api_key,
                "anthropic": self.anthropic_api_key}.get(provider, "")

    def validate_llm_config(self) -> None:
        """Fail fast at startup if the default provider has no key.

        Requests may still override `provider`; a missing key for that
        provider surfaces as a 400 at request time (see llm_client).
        """
        # Imported here, not at module scope: config is imported by almost
        # everything and the provider registry pulls in httpx. The list must
        # come from the registry -- when these two drifted apart, a provider
        # that was fully implemented could not be selected, and the failure was
        # a startup SystemExit that read like a typo in .env.
        from app.services.llm_providers import PROVIDERS

        if self.llm_provider not in PROVIDERS:
            raise SystemExit(
                f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, got {self.llm_provider!r}"
            )
        if not self.api_key_for(self.llm_provider):
            raise SystemExit(
                f"{self.llm_provider.upper()}_API_KEY is not set (LLM_PROVIDER={self.llm_provider}). "
                "Copy backend/.env.example to backend/.env and fill it in."
            )

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
