from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env, resolved by absolute path so the API loads it no matter what
# directory uvicorn is launched from (root or apps/api). A local ".env" is also
# read for Docker/Railway where the app dir is the working directory; real
# environment variables still take precedence over both.
_CONFIG_PATH = Path(__file__).resolve()
_ROOT_ENV = (
    _CONFIG_PATH.parents[3] / ".env"
    if len(_CONFIG_PATH.parents) > 3
    else _CONFIG_PATH.parents[1] / ".env"
)


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / root .env."""

    model_config = SettingsConfigDict(env_file=(str(_ROOT_ENV), ".env"), extra="ignore")

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

    # Routing / pathfinding. Slippage buffer added to the discovered source
    # amount when capping Payment.SendMax (basis points). Partial payments add
    # DeliverMin + tfPartialPayment so a payment still lands if a path narrows.
    route_slippage_bps: int = 50
    route_partial_payment: bool = False

    # XRPL Credentials (XLS-70) KYC layer. When enabled, the receiver must hold
    # an accepted, non-expired credential of `credential_type` issued by
    # `credential_issuer_address`; otherwise compliance raises a risk flag (which
    # can push the payment to hardware approval — code decides, never the LLM).
    # `credential_issuer_seed` lets the treasury act as the issuer for
    # CredentialCreate; never commit a real seed.
    credential_kyc_enabled: bool = True
    credential_type: str = "KYC"
    credential_issuer_address: str = ""
    credential_issuer_seed: str = ""
    # Subject-side seed used by the credential agent's accept step on Testnet
    # (CredentialAccept must be signed by the subject). Demo/testing only; never
    # commit a real seed. Left empty in production where subjects accept their own.
    credential_subject_seed: str = ""

    frankfurter_base_url: str = "https://api.frankfurter.dev/v1"

    opensanctions_api_key: str = ""
    opensanctions_base_url: str = "https://api.opensanctions.org"
    opensanctions_dataset: str = "sanctions"
    opensanctions_match_threshold: float = 0.85
    public_intel_enabled: bool = False

    # Hex secp256k1 public key the Firefly device signs with; release is refused
    # unless the approval signature verifies against this key.
    firefly_public_key: str = ""

    # XRPL network identifier included in the approval payload to prevent
    # testnet signatures from being replayed on mainnet.
    xrpl_network: str = "xrpl:1"

    # XRPL address of the treasury wallet that owns the escrows. Included in
    # the approval payload so the device commits to the exact escrow owner.
    # In mock mode an empty string falls back to "r_TREASURY_MOCK".
    treasury_wallet_address: str = ""

    # When true, XRPL submission is mocked with deterministic fake tx hashes so
    # the full flow runs offline (demo fallback / local dev without a wallet).
    use_mock_xrpl: bool = True

    # Testnet has no real value, so a genuine $10k+ payment can't be funded in XRP
    # (the faucet gives ~100 XRP, not the ~12,000 a $15k payment routes to). This
    # factor scales ONLY the on-ledger settlement amount (the XRP/token actually
    # locked in escrow or paid) so the escrow→Firefly-release flow is provable on
    # a real ledger. Policy, compliance, audit, and the Firefly approval digest all
    # use the TRUE intent amount — the human still approves the real figure. The
    # audit log records the scaling. 1.0 = no scaling (production default).
    testnet_settlement_scale: float = 1.0

    # When true, the deliberate-tamper demo endpoint is available. Never enable
    # in production — it exists solely to prove signature binding on stage.
    demo_mode: bool = False

    # Autonomous treasury agent. `agent_max_amount_usd` is a defense-in-depth cap:
    # the agent will not initiate a payment whose source amount (in the goal's
    # currency) exceeds this before even calling the orchestrator. The policy gate
    # still runs after that and may escalate large amounts to Firefly approval.
    agent_enabled: bool = True
    agent_max_amount_usd: float = 50_000.0
    # Country code the treasury agent reports as its own origin (CH for SwissHacks).
    agent_sender_country: str = "CH"

    # XLS-65 Single Asset Vault + XLS-66 yield. Disabled by default — requires
    # the XLS-65 amendment which is available on Devnet but may not be on
    # Testnet yet. vault_id is set after the first VaultCreate and stored here.
    # sweep: deposit excess above vault_sweep_threshold_usd on each agent cycle;
    # recall: withdraw when wallet balance falls below vault_recall_threshold_usd.
    vault_enabled: bool = False
    vault_xrpl_endpoint: str = "wss://s.devnet.rippletest.net:51233"
    vault_sweep_threshold_usd: float = 5_000.0
    vault_recall_threshold_usd: float = 1_000.0
    vault_id: str = ""  # hex LedgerIndex of the Vault object; set after VaultCreate

    # ARS x402 pay-at-need. When enabled, the agent can pay for external services
    # that respond with HTTP 402. Facilitator URL is the t54 x402 facilitator.
    # Allowed assets and facilitators are allowlisted here; the x402 tool rejects
    # any challenge that requests a currency or facilitator not in these lists.
    # Agent spend scope (G4): caps per single x402 call and rolling 24-hour window.
    x402_enabled: bool = False
    x402_facilitator_url: str = "https://xrpl-facilitator-testnet.t54.ai"
    x402_allowed_assets: str = "RLUSD"          # comma-separated currency codes
    x402_allowed_facilitators: str = "https://xrpl-facilitator-testnet.t54.ai"  # comma-sep URLs
    x402_scope_max_per_tx_usd: float = 50.0     # G4 per-transaction cap
    x402_scope_max_per_day_usd: float = 500.0   # G4 rolling 24h cap
    x402_allowed_service_hosts: str = ""        # comma-sep; empty = any host allowed
    x402_source_tag: int = 20260530             # Starter Kit convention
    x402_demo_enabled: bool = False             # local/test merchant resource only
    x402_demo_pay_to: str = ""                  # trust-lined Testnet recipient
    x402_demo_price: str = "1.000000"           # exact RLUSD amount

    # ARS Agent-to-Agent Delegation (G5). When enabled, the orchestrator accepts
    # grant_delegation / sub-agent payment calls. delegation_default_max_total is
    # the hard ceiling any single grant may authorise; individual grants may be lower.
    delegation_enabled: bool = False
    delegation_default_max_total_usd: float = 1_000.0
    delegation_default_max_per_tx_usd: float = 100.0
    delegation_default_max_per_day_usd: float = 250.0

    # ARS Trade Finance (on-chain credit, XLS-65 vault-backed early payment).
    # discount_rate_default is the fraction deducted from face value when paying
    # early (e.g. 0.02 = 2 %).
    trade_finance_enabled: bool = False
    trade_finance_discount_rate_default: float = 0.02
    trade_finance_source_tag: int = 20260530

    # ARS XLS-66 Lending (LoanBroker / LoanSet / LoanCreate / LoanRepay).
    # Amendment-gated — Devnet only at build time. If the amendment check fails
    # at demo time, flip this to false and fall back to XLS-65 early payment.
    lending_enabled: bool = False
    lending_xrpl_endpoint: str = "wss://s.devnet.rippletest.net:51233"
    lending_loan_broker_address: str = ""  # LoanBroker account on Devnet
    lending_source_tag: int = 20260530

    # XLS-33 MPTokens — COMPLY compliance-attestation issuance.
    # Disabled by default. XLS-33 is available on Testnet and Devnet.
    # mpt_xrpl_endpoint defaults to xrpl_endpoint when empty.
    # mpt_issuance_id is set after MPTokenIssuanceCreate.
    # mpt_recipient_address + mpt_recipient_seed enable real-mode minting
    # (the recipient must call their own MPTokenAuthorize first).
    mpt_enabled: bool = False
    mpt_xrpl_endpoint: str = ""  # defaults to xrpl_endpoint when empty
    mpt_issuance_id: str = ""
    mpt_recipient_address: str = ""
    mpt_recipient_seed: str = ""

    # Comma-separated browser origins allowed to call the API.
    cors_origins: str = (
        "http://localhost:5173,"
        "http://localhost:4173,"
        "https://web-production-cba3.up.railway.app"
    )

    # Railway preview/prod service hosts plus Cloudflare Pages (*.pages.dev).
    # Local loopback origins are added separately in main.py so local .env
    # overrides cannot disable Vite development on a fallback port.
    cors_origin_regex: str = r"https://.*\.(up\.railway\.app|railway\.app|pages\.dev)"

    # Injected by Railway. When the web service URL changes, include it without
    # requiring a manual CORS_ORIGINS update during rehearsal.
    railway_service_web_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
