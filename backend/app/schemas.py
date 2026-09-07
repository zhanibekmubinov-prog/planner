"""Схемы API. v0.8: строгая валидация входа (С3/С6), корзина (deleted_at), перенос проекта, версия задачи (updated_at)."""
import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from .models import Channel, DelegationStatus, DirectionStatus, Recipient, TaskStatus, ToolType

# Длины совпадают с String(N) в models.py — иначе Postgres ответит 500 вместо 422
Name200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Title300 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Priority = Annotated[int, Field(ge=1, le=5)]  # 1 высокий … 5 низкий
PAST_TOLERANCE = timedelta(minutes=5)  # запас на рассинхрон часов клиента
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def dedupe(ids: list) -> list:
    """Убрать повторы, сохранив порядок: tool_ids [1, 1] иначе даёт IntegrityError (С3)."""
    return list(dict.fromkeys(ids))


def ensure_not_past(dt: datetime | None, what: str) -> datetime | None:
    """Дата не раньше «сейчас − 5 минут»: напоминание в прошлом ушло бы на первом же тике планировщика (В3)."""
    if dt is None:
        return dt
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if aware < datetime.now(timezone.utc) - PAST_TOLERANCE:
        raise ValueError(f"{what}: время уже прошло — укажите время в будущем")
    return dt


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: int
    email: str
    name: str
    is_admin: bool
    telegram_chat_id: str | None = None
    digest_enabled: bool = True

class GuestIn(BaseModel):
    """Приглашение внешнего участника (v0.10). Добавляет только админ."""
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]
    name: Name200
    note: str | None = Field(None, max_length=500)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.lower()
        if not EMAIL_RE.match(v):
            raise ValueError("укажите адрес вида имя@домен")
        return v


class GuestOut(ORM):
    id: int
    email: str
    name: str
    note: str | None = None
    created_at: datetime
    invited_by_id: int | None = None
    last_login_at: datetime | None = None      # из учётной записи гостя, если он уже входил
    has_password: bool = False                 # задал ли он себе пароль (v0.10.1)
    password_set_at: datetime | None = None


class GuestLoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]


class GuestVerifyIn(BaseModel):
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=200)]


class GuestPasswordIn(BaseModel):
    """Гость задаёт себе пароль (v0.10.1). Требования проверяет guests.password_problem."""
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class GuestPasswordLoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class UserBrief(ORM):
    id: int
    name: str
    email: str

class ProfileIn(BaseModel):
    name: Name200
    telegram_chat_id: str | None = Field(None, max_length=64)
    digest_enabled: bool = True


class DirectionIn(BaseModel):
    name: Name200
    description: str | None = None
    goal: str | None = None
    color: Color | None = None
    status: DirectionStatus = DirectionStatus.active

class DirectionOut(ORM):
    id: int
    name: str
    description: str | None = None
    goal: str | None = None
    color: str | None = None
    status: DirectionStatus
    created_at: datetime
    owner: UserBrief | None = None
    access: str | None = None   # owner | edit | view | via (см. scope.py)
    deleted_at: datetime | None = None   # заполнено только в корзине (GET /trash)


class ProjectIn(BaseModel):
    direction_id: int
    name: Name200
    description: str | None = None
    goal: str | None = None
    color: Color | None = None
    status: DirectionStatus = DirectionStatus.active
    # Перенос в другое направление (только при смене direction_id): move — задачи теряют старое направление,
    # copy — остаются в обоих; grant_access_user_ids — кому из имевших доступ через старое направление открыть проект
    move_mode: Literal["move", "copy"] = "move"
    grant_access_user_ids: list[int] = []

    _dedupe_grants = field_validator("grant_access_user_ids")(classmethod(lambda cls, v: dedupe(v)))

    def db_fields(self) -> dict:
        """Поля, которые пишутся в модель (без служебных параметров переноса)."""
        return self.model_dump(exclude={"move_mode", "grant_access_user_ids"})

class ProjectOut(ORM):
    id: int
    direction_id: int
    name: str
    description: str | None = None
    goal: str | None = None
    color: str | None = None
    status: DirectionStatus
    created_at: datetime
    owner: UserBrief | None = None
    access: str | None = None
    deleted_at: datetime | None = None


class AccessPreviewRow(BaseModel):
    """GET /projects/{id}/access-preview: кто сейчас видит проект и сохранит ли доступ после переноса."""
    user: UserBrief
    permission: str            # view | edit
    keeps_access: bool


class Impact(BaseModel):
    """GET /directions|projects/{id}/impact — числа для текста подтверждения удаления."""
    projects: int = 0
    tasks: int = 0
    open_tasks: int = 0
    shares: int = 0


class ShareIn(BaseModel):
    entity_type: str        # direction | project | task
    entity_id: int
    email: str
    permission: str = "view"  # view | edit

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Укажите рабочую почту, например n.abilkhanov@cis.kz")
        return v

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
    id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    done: bool = False


class TaskIn(BaseModel):
    title: Title300
    description: str | None = None
    status: TaskStatus = TaskStatus.backlog
    priority: Priority = 3
    deadline: date | None = None
    next_check_at: datetime | None = None
    direction_ids: list[int] = []
    tool_ids: list[int] = []
    project_id: int | None = None
    checklist: list[ChecklistItem] = []
    # Версия карточки (С5): если передана и отличается от сохранённой — 409, чтобы автосохранение
    # одного окна не затирало правки другого. Старые клиенты поле не шлют — проверка не выполняется.
    updated_at: datetime | None = None

    _dedupe_ids = field_validator("direction_ids", "tool_ids")(classmethod(lambda cls, v: dedupe(v)))

    @field_validator("checklist")
    @classmethod
    def _unique_checklist_ids(cls, v: list[ChecklistItem]) -> list[ChecklistItem]:
        ids = [i.id for i in v]
        if len(ids) != len(set(ids)):
            raise ValueError("В чеклисте повторяются id пунктов")
        return v

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
    directions: list[DirectionOut]     # только живые направления (см. Task.directions в models.py)
    tools: list["ToolOut"]
    owner: UserBrief | None = None
    project_id: int | None = None      # отдаётся как есть; проект в корзине фронт трактует как «без проекта»
    checklist: list[ChecklistItem] = []
    access: str | None = None          # owner | edit | view | assignee
    assigned_to_me: bool = False
    deleted_at: datetime | None = None


class TrashOut(BaseModel):
    """GET /trash — моя корзина."""
    directions: list[DirectionOut] = []
    projects: list[ProjectOut] = []
    tasks: list[TaskOut] = []


class PersonIn(BaseModel):
    name: Name200
    telegram_chat_id: str | None = Field(None, max_length=64)
    email: str | None = Field(None, max_length=200)
    note: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        v = (v or "").strip().lower() or None
        if v and not EMAIL_RE.match(v):
            raise ValueError("Некорректный e-mail")
        return v

class PersonOut(ORM):
    id: int
    name: str
    telegram_chat_id: str | None = None
    email: str | None = None
    note: str | None = None
    user_id: int | None = None


class DelegationBase(BaseModel):
    task_id: int
    person_id: int
    check_at: datetime | None = None
    comment: str | None = None
    status: DelegationStatus = DelegationStatus.open

class DelegationIn(DelegationBase):
    """POST /delegations: дата проверки не в прошлом."""
    _check_at = field_validator("check_at")(classmethod(lambda cls, v: ensure_not_past(v, "Дата проверки")))

class DelegationUpdate(DelegationBase):
    """PUT /delegations/{id}: task_id игнорируется (К1); «не в прошлом» проверяется в роутере, только если check_at изменился."""

class DelegationOut(DelegationBase, ORM):
    id: int
    assigned_at: datetime
    notified_at: datetime | None = None
    report: str | None = None
    person: PersonOut


class DelegationReportIn(BaseModel):
    status: DelegationStatus
    report: str | None = None


class ToolIn(BaseModel):
    name: Name200
    type: ToolType = ToolType.other
    url: str | None = Field(None, max_length=1000)
    source_ref: dict | None = None
    note: str | None = None
    task_ids: list[int] = []
    direction_ids: list[int] = []

    _dedupe_ids = field_validator("task_ids", "direction_ids")(classmethod(lambda cls, v: dedupe(v)))

class ToolOut(ORM):
    id: int
    name: str
    type: ToolType
    url: str | None
    source_ref: dict | None
    note: str | None
    direction_ids: list[int] = []   # привязки к направлениям — фронт возвращает их при правке тула (С8)


class ReminderBase(BaseModel):
    task_id: int
    fire_at: datetime
    channels: list[Channel] = Field([Channel.telegram], min_length=1)
    message: str | None = None
    recipient: Recipient = Recipient.owner

    _dedupe_channels = field_validator("channels")(classmethod(lambda cls, v: dedupe(v)))

class ReminderIn(ReminderBase):
    """POST /reminders: время не в прошлом."""
    _fire_at = field_validator("fire_at")(classmethod(lambda cls, v: ensure_not_past(v, "Время напоминания")))

class ReminderUpdate(ReminderBase):
    """PUT /reminders/{id}: task_id игнорируется (В3); «не в прошлом» проверяется в роутере, только если fire_at изменился."""

class ReminderOut(ReminderBase, ORM):
    id: int
    sent_at: datetime | None


class MindMapIn(BaseModel):
    title: Title300
    direction_id: int | None = None
    task_id: int | None = None
    data: dict

class MindMapOut(ORM):
    id: int
    title: str
    direction_id: int | None = None
    task_id: int | None = None
    data: dict
    created_at: datetime
    updated_at: datetime


TaskOut.model_rebuild()
