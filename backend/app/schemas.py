from datetime import date, datetime
from pydantic import BaseModel, ConfigDict
from .models import Channel, DelegationStatus, DirectionStatus, TaskStatus, ToolType


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DirectionIn(BaseModel):
    name: str
    description: str | None = None
    goal: str | None = None
    color: str | None = None
    status: DirectionStatus = DirectionStatus.active

class DirectionOut(DirectionIn, ORM):
    id: int
    created_at: datetime


class TaskIn(BaseModel):
    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.backlog
    priority: int = 3
    deadline: date | None = None
    next_check_at: datetime | None = None
    direction_ids: list[int] = []
    tool_ids: list[int] = []

class TaskOut(ORM):
    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: int
    deadline: date | None
    next_check_at: datetime | None
    outlook_event_id: str | None
    created_at: datetime
    updated_at: datetime
    directions: list[DirectionOut]
    tools: list["ToolOut"]


class PersonIn(BaseModel):
    name: str
    telegram_chat_id: str | None = None
    email: str | None = None
    note: str | None = None

class PersonOut(PersonIn, ORM):
    id: int


class DelegationIn(BaseModel):
    task_id: int
    person_id: int
    check_at: datetime | None = None
    comment: str | None = None
    status: DelegationStatus = DelegationStatus.open

class DelegationOut(DelegationIn, ORM):
    id: int
    assigned_at: datetime
    person: PersonOut


class ToolIn(BaseModel):
    name: str
    type: ToolType = ToolType.other
    url: str | None = None
    source_ref: dict | None = None
    note: str | None = None
    task_ids: list[int] = []
    direction_ids: list[int] = []

class ToolOut(ORM):
    id: int
    name: str
    type: ToolType
    url: str | None
    source_ref: dict | None
    note: str | None


class ReminderIn(BaseModel):
    task_id: int
    fire_at: datetime
    channels: list[Channel] = [Channel.telegram]
    message: str | None = None

class ReminderOut(ReminderIn, ORM):
    id: int
    sent_at: datetime | None


TaskOut.model_rebuild()
