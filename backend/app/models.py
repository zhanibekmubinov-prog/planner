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


class Direction(Base):
    __tablename__ = "directions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[DirectionStatus] = mapped_column(Enum(DirectionStatus), default=DirectionStatus.active)
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
    tasks: Mapped[list[Task]] = relationship(secondary=tool_tasks, back_populates="tools")
    directions: Mapped[list[Direction]] = relationship(secondary=tool_directions, back_populates="tools")


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channels: Mapped[list] = mapped_column(JSON, default=list)  # ["telegram","email","outlook_calendar"]
    message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[Task] = relationship(back_populates="reminders")


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
