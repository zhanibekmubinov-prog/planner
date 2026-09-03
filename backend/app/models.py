import enum
from datetime import date, datetime
from sqlalchemy import JSON, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class DirectionStatus(str, enum.Enum):
    active = "active"; paused = "paused"; archived = "archived"

class TaskStatus(str, enum.Enum):
    backlog = "backlog"; in_progress = "in_progress"; waiting = "waiting"; done = "done"

class DelegationStatus(str, enum.Enum):
    open = "open"; done = "done"

class ToolType(str, enum.Enum):
    google_sheet = "google_sheet"; excel_sharepoint = "excel_sharepoint"
    telegram_bot = "telegram_bot"; notion = "notion"; other = "other"

class Channel(str, enum.Enum):
    telegram = "telegram"; email = "email"; outlook_calendar = "outlook_calendar"

class Recipient(str, enum.Enum):
    """Кому уходит напоминание: владельцу задачи, исполнителям (открытые поручения) или обоим."""
    owner = "owner"; assignees = "assignees"; both = "both"


# --- many-to-many link tables (задачи и тулы кросс-направленческие) ---
task_directions = Table("task_directions", Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("direction_id", ForeignKey("directions.id", ondelete="CASCADE"), primary_key=True))
tool_tasks = Table("tool_tasks", Base.metadata,
    Column("tool_id", ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True))
tool_directions = Table("tool_directions", Base.metadata,
    Column("tool_id", ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
    Column("direction_id", ForeignKey("directions.id", ondelete="CASCADE"), primary_key=True))


class User(Base):
    """Пользователь планнера. Создаётся автоматически при первом входе через Microsoft."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    ms_oid: Mapped[str | None] = mapped_column(String(64), unique=True)   # object id в Entra
    is_admin: Mapped[bool] = mapped_column(default=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    digest_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Direction(Base):
    __tablename__ = "directions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[DirectionStatus] = mapped_column(Enum(DirectionStatus), default=DirectionStatus.active)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tasks: Mapped[list["Task"]] = relationship(secondary=task_directions, back_populates="directions")
    tools: Mapped[list["Tool"]] = relationship(secondary=tool_directions, back_populates="directions")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.backlog)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 высокий … 5 низкий
    deadline: Mapped[date | None] = mapped_column(Date)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outlook_event_id: Mapped[str | None] = mapped_column(String(300))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    owner: Mapped["User | None"] = relationship()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    directions: Mapped[list[Direction]] = relationship(secondary=task_directions, back_populates="tasks")
    tools: Mapped[list["Tool"]] = relationship(secondary=tool_tasks, back_populates="tasks")
    delegations: Mapped[list["Delegation"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)  # если человек зашёл в планнер
    user: Mapped["User | None"] = relationship()


class Delegation(Base):
    __tablename__ = "delegations"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DelegationStatus] = mapped_column(Enum(DelegationStatus), default=DelegationStatus.open)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # когда отправлено «пора проверить»
    report: Mapped[str | None] = mapped_column(Text)  # отчёт исполнителя
    assigned_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # исполнителю сообщили о поручении
    task: Mapped[Task] = relationship(back_populates="delegations")
    person: Mapped[Person] = relationship()


class Tool(Base):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[ToolType] = mapped_column(Enum(ToolType), default=ToolType.other)
    url: Mapped[str | None] = mapped_column(String(1000))
    # для агентов: {"spreadsheet_id": ...} / {"drive_id":..., "item_id":...} / {"bot_username":...}
    source_ref: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    tasks: Mapped[list[Task]] = relationship(secondary=tool_tasks, back_populates="tools")
    directions: Mapped[list[Direction]] = relationship(secondary=tool_directions, back_populates="tools")


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channels: Mapped[list] = mapped_column(JSON, default=list)  # ["telegram","email","outlook_calendar"]
    message: Mapped[str | None] = mapped_column(Text)
    recipient: Mapped[str] = mapped_column(String(16), default="owner", server_default="owner")  # owner | assignees | both
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[Task] = relationship(back_populates="reminders")


class MindMap(Base):
    """Майндмап: дерево узлов в JSON. Может быть привязан к направлению и/или задаче, либо жить сам по себе."""
    __tablename__ = "mindmaps"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    direction_id: Mapped[int | None] = mapped_column(ForeignKey("directions.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    # {"id": "root", "text": "...", "children": [{"id": "...", "text": "...", "children": [...], "collapsed": false}]}
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    direction: Mapped["Direction | None"] = relationship()
    task: Mapped["Task | None"] = relationship()


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- MCP-коннектор: OAuth 2.0 для Claude (claude.ai / мобильное приложение / Claude Desktop) ---
class McpClient(Base):
    """Клиент, зарегистрированный через Dynamic Client Registration (Claude регистрируется сам)."""
    __tablename__ = "mcp_clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(128))
    redirect_uris: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class McpPendingAuth(Base):
    """Запрос авторизации, ожидающий входа через Microsoft и согласия пользователя (живёт 10 минут)."""
    __tablename__ = "mcp_pending_auth"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    redirect_uri: Mapped[str] = mapped_column(String(1000))
    state: Mapped[str | None] = mapped_column(String(500))
    code_challenge: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str | None] = mapped_column(String(200))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class McpAuthCode(Base):
    __tablename__ = "mcp_auth_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(String(1000))
    code_challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(default=False)


class McpToken(Base):
    """В базе только SHA-256 хеши токенов. Access живёт 8 ч, refresh — 30 дней с ротацией."""
    __tablename__ = "mcp_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
