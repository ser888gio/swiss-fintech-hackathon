from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / root .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/treasury"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    xrpl_endpoint: str = "wss://s.altnet.rippletest.net:51233"
    treasury_wallet_seed: str = ""
    release_wallet_seed: str = ""
    token_issuer_address: str = ""
    token_currency: str = "USD"

    policy_threshold_usd: float = 10_000.0
    policy_compliance_flag_score: int = 60

    frankfurter_base_url: str = "https://api.frankfurter.dev/v1"

    opensanctions_api_key: str = ""
    opensanctions_base_url: str = "https://api.opensanctions.org"
    opensanctions_dataset: str = "sanctions"
    opensanctions_match_threshold: float = 0.85
    public_intel_enabled: bool = False

    # Hex secp256k1 public key the Firefly device signs with; release is refused
    # unless the approval signature verifies against this key.
    firefly_public_key: str = ""

    # When true, XRPL submission is mocked with deterministic fake tx hashes so
    # the full flow runs offline (demo fallback / local dev without a wallet).
    use_mock_xrpl: bool = True

    # When true, the deliberate-tamper demo endpoint is available. Never enable
    # in production — it exists solely to prove signature binding on stage.
    demo_mode: bool = False

    # Comma-separated browser origins allowed to call the API.
    cors_origins: str = (
        "http://localhost:5173,"
        "http://localhost:4173,"
        "https://web-production-cba3.up.railway.app"
    )

    # Railway preview/prod service hosts. Keep explicit origins above for the
    # main demo URL; this catches regenerated Railway domains during rehearsals.
    cors_origin_regex: str = r"https://.*\.(up\.railway\.app|railway\.app)"

    # Injected by Railway. When the web service URL changes, include it without
    # requiring a manual CORS_ORIGINS update during rehearsal.
    railway_service_web_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
