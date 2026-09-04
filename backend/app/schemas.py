from datetime import date, datetime
from pydantic import BaseModel, ConfigDict
from .models import Channel, DelegationStatus, DirectionStatus, Recipient, TaskStatus, ToolType


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: int
    email: str
    name: str
    is_admin: bool
    telegram_chat_id: str | None = None
    digest_enabled: bool = True

class UserBrief(ORM):
    id: int
    name: str
    email: str

class ProfileIn(BaseModel):
    name: str
    telegram_chat_id: str | None = None
    digest_enabled: bool = True


class DirectionIn(BaseModel):
    name: str
    description: str | None = None
    goal: str | None = None
    color: str | None = None
    status: DirectionStatus = DirectionStatus.active

class DirectionOut(DirectionIn, ORM):
    id: int
    created_at: datetime
    owner: UserBrief | None = None
    access: str | None = None   # owner | edit | view | via (см. scope.py)


class ProjectIn(BaseModel):
    direction_id: int
    name: str
    description: str | None = None
    goal: str | None = None
    color: str | None = None
    status: DirectionStatus = DirectionStatus.active

class ProjectOut(ProjectIn, ORM):
    id: int
    created_at: datetime
    owner: UserBrief | None = None
    access: str | None = None


class ShareIn(BaseModel):
    entity_type: str        # direction | project | task
    entity_id: int
    email: str
    permission: str = "view"  # view | edit

class SharePermissionIn(BaseModel):
    permission: str

class ShareOut(ORM):
    id: int
    entity_type: str
    entity_id: int
    permission: str
    user: UserBrief
    created_at: datetime

class SharedWithMe(BaseModel):
    """Строка раздела «Общие»: что и кто мне открыл."""
    entity_type: str
    entity_id: int
    permission: str
    name: str
    direction_id: int | None = None
    shared_by: UserBrief | None = None
    created_at: datetime


class ChecklistItem(BaseModel):
    id: str
    text: str
    done: bool = False


class TaskIn(BaseModel):
    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.backlog
    priority: int = 3
    deadline: date | None = None
    next_check_at: datetime | None = None
    direction_ids: list[int] = []
    tool_ids: list[int] = []
    project_id: int | None = None
    checklist: list[ChecklistItem] = []

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
    owner: UserBrief | None = None
    project_id: int | None = None
    checklist: list[ChecklistItem] = []
    access: str | None = None          # owner | edit | view | assignee
    assigned_to_me: bool = False


class PersonIn(BaseModel):
    name: str
    telegram_chat_id: str | None = None
    email: str | None = None
    note: str | None = None

class PersonOut(PersonIn, ORM):
    id: int
    user_id: int | None = None


class DelegationIn(BaseModel):
    task_id: int
    person_id: int
    check_at: datetime | None = None
    comment: str | None = None
    status: DelegationStatus = DelegationStatus.open

class DelegationOut(DelegationIn, ORM):
    id: int
    assigned_at: datetime
    notified_at: datetime | None = None
    report: str | None = None
    person: PersonOut


class DelegationReportIn(BaseModel):
    status: DelegationStatus
    report: str | None = None


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
    recipient: Recipient = Recipient.owner

class ReminderOut(ReminderIn, ORM):
    id: int
    sent_at: datetime | None


class MindMapIn(BaseModel):
    title: str
    direction_id: int | None = None
    task_id: int | None = None
    data: dict

class MindMapOut(MindMapIn, ORM):
    id: int
    created_at: datetime
    updated_at: datetime


TaskOut.model_rebuild()
