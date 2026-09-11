from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRETS = ("change-me", "change-me-too")


class Settings(BaseSettings):
    database_url: str
    api_token: str = "change-me"
    cors_origins: str = "http://localhost:5173"

    # --- Пользователи и вход через Microsoft (делегированный OIDC) ---
    owner_email: str = ""          # владелец/админ: этот пользователь получает старые данные и права админа
    session_secret: str = "change-me-too"   # подпись наших сессионных JWT
    session_days: int = 30
    ms_redirect_uri: str = ""      # https://<backend>/api/auth/callback — должен совпадать с Entra
    allowed_email_domains: str = ""  # напр. "cis.kz" — пусто = любой домен тенанта

    # --- Вход из платформы CIS (планнер открыт вкладкой внутри платформы) ---
    # Платформа опознаёт сотрудника своим входом Microsoft и выдаёт одноразовый билет,
    # подписанный этим секретом; мы меняем билет на свою сессию (см. routers/auth.py).
    # Пусто = вход из платформы выключен.
    platform_sso_secret: str = ""
    platform_ticket_max_age_sec: int = 120   # потолок возраста билета, даже если платформа выписала длиннее

    # --- Напоминания (шаг 4). Пустое значение = канал выключен. ---
    scheduler_enabled: bool = True
    scheduler_interval_sec: int = 60
    app_timezone: str = "Asia/Oral"          # для форматирования времени в сообщениях
    frontend_url: str = ""                    # ссылка «открыть в планнере» в сообщениях
    public_url: str = ""                      # публичный адрес бэкенда для OAuth-метаданных MCP; пусто = берём из заголовков запроса

    # Утренняя сводка: время по app_timezone, каналы через запятую; пусто = выключено
    digest_time: str = "08:30"
    digest_channels: str = "telegram,email"
    digest_weekdays_only: bool = False

    telegram_bot_token: str = ""              # от @BotFather
    telegram_chat_id: str = ""                # ваш chat id (владелец планнера)
    telegram_bot_username: str = ""           # имя бота без @, напр. cisplannerbot — для кнопки «Подключить Telegram»
    telegram_webhook_secret: str = ""         # секрет вебхука бота (задаётся в setWebhook); пусто = вебхук выключен

    # Microsoft Graph — приложение в Azure AD с правами Mail.Send и Calendars.ReadWrite (application)
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_mailbox: str = ""                      # почтовый ящик, от имени которого шлём и в чей календарь пишем, напр. zh.mubinov@cis.kz
    notify_email_to: str = ""                 # куда слать напоминания (по умолчанию = ms_mailbox)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("api_token", "session_secret")
    @classmethod
    def _secret_is_real(cls, v: str, info):
        """К2: с дефолтным или коротким секретом приложение не стартует — иначе любой подделает JWT владельца."""
        v = (v or "").strip()
        if v in _DEFAULT_SECRETS or v.startswith("change-me") or len(v) < 16:
            env = info.field_name.upper()
            raise ValueError(f"{env}: задайте случайную строку не короче 16 символов (сейчас значение по умолчанию или слишком короткое). "
                             f"Например: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        return v

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def digest_channel_list(self) -> list[str]:
        return [c.strip() for c in self.digest_channels.split(",") if c.strip()]

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_email_domains.split(",") if d.strip()]

    @property
    def platform_sso_ready(self) -> bool:
        return len(self.platform_sso_secret.strip()) >= 16

    @property
    def ms_login_ready(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret and self.ms_redirect_uri)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def graph_ready(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret and self.ms_mailbox)


settings = Settings()
