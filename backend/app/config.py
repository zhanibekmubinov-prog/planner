from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    api_token: str = "change-me"
    cors_origins: str = "http://localhost:5173"

    # --- Напоминания (шаг 4). Пустое значение = канал выключен. ---
    scheduler_enabled: bool = True
    scheduler_interval_sec: int = 60
    app_timezone: str = "Asia/Oral"          # для форматирования времени в сообщениях
    frontend_url: str = ""                    # ссылка «открыть в планнере» в сообщениях

    # Утренняя сводка: время по app_timezone, каналы через запятую; пусто = выключено
    digest_time: str = "08:30"
    digest_channels: str = "telegram,email"
    digest_weekdays_only: bool = False

    telegram_bot_token: str = ""              # от @BotFather
    telegram_chat_id: str = ""                # ваш chat id (владелец планнера)

    # Microsoft Graph — приложение в Azure AD с правами Mail.Send и Calendars.ReadWrite (application)
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_mailbox: str = ""                      # почтовый ящик, от имени которого шлём и в чей календарь пишем, напр. zh.mubinov@cis.kz
    notify_email_to: str = ""                 # куда слать напоминания (по умолчанию = ms_mailbox)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def digest_channel_list(self) -> list[str]:
        return [c.strip() for c in self.digest_channels.split(",") if c.strip()]

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def graph_ready(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret and self.ms_mailbox)


settings = Settings()
