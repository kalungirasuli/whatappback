from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_webhook_verify_token: str = ""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/whatappseller"

    redis_url: str = "redis://localhost:6379/0"

    queue_type: str = "memory"
    sqs_queue_url: str = ""
    rabbitmq_url: str = ""
    bullmq_redis_url: str = ""

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "whatappseller-images"
    cdn_base_url: str = "http://localhost:9000/whatappseller-images"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "products"

    admin_jwt_secret: str = "change-me-in-production"
    admin_session_expire_hours: int = 8

    jwt_secret: str = "change-me-in-production-jwt-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 4320
    jwt_refresh_expire_days: int = 30
    otp_expire_seconds: int = 300
    otp_rate_limit_enabled: bool = True
    otp_rate_limit_per_phone: int = 3
    otp_rate_limit_window_seconds: int = 900

    api_host: str = "0.0.0.0"
    api_port: int = 8002

    rate_limit_per_phone: int = 10
    rate_limit_window_seconds: int = 60
    rate_limit_per_ip: int = 100
    register_rate_limit_per_number: int = 3
    register_rate_limit_window_hours: int = 24

    new_merchant_window_days: int = 7
    new_merchant_max_listings_per_day: int = 3

    siglip_model: str = "google/siglip-base-patch16-224"
    siglip_dim: int = 768
    dinov2_model: str = "facebook/dinov2-base"
    dinov2_dim: int = 768
    text_embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    text_embedding_dim: int = 768
    yolo_confidence: float = 0.5
    moderation_max_size_mb: int = 10

    siglip_weight: float = 0.6
    dinov2_weight: float = 0.4

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma2:2b"
    ollama_timeout: int = 15
    nlu_fallback_to_regex: bool = True

    llm_api_url: str = "http://localhost:11434"
    llm_api_key: str = "ollama"
    llm_model: str = "gemma2:2b"

    log_level: str = "INFO"


settings = Settings()
