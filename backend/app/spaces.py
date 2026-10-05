"""Слои (v1.7): «Личное» и «Организация».

Решения владельца (2026-10-05):

* Слой живёт **на направлении**. Проекты и майндмапы наследуют слой своего направления —
  отдельного поля у них нет. У задачи слой вычисляется из её живых направлений
  (задачи кросс-направленческие: лежит и в личном, и в рабочем — видна в обоих);
  у задачи без живых направлений слой свой — `Task.space`.
* Попадание **автоматическое с возможностью переопределить**: пока владелец не поставил
  слой руками (`Direction.space_pinned`), первое «Поделиться» или первое поручение
  другому человеку переводит направление в «Организацию». Поставил руками — автоправило
  больше не вмешивается.
* Фильтрация слоёв — на фронте: бэкенд отдаёт поле `space` у направлений и задач,
  отдельных «слойных» эндпоинтов нет. Так переключение слоя не стоит ни одного запроса
  (важно: сервисы в sfo, а владелец в Атырау — каждый лишний запрос это ~300 мс).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

PERSONAL = "personal"
ORG = "org"
SPACES = (PERSONAL, ORG)


def task_space(task: models.Task) -> str:
    """Слой задачи: «Организация», если хоть одно живое направление рабочее;
    иначе «Личное», если живые направления есть; иначе собственный слой задачи."""
    dirs = [d for d in task.directions if d.deleted_at is None]
    if not dirs:
        return task.space or PERSONAL
    return ORG if any(d.space == ORG for d in dirs) else PERSONAL


def directions_touched(db: Session, entity_type: str, entity_id: int) -> list[models.Direction]:
    """Направления, которых касается доступ или поручение к этой сущности."""
    if entity_type == "direction":
        d = db.get(models.Direction, entity_id)
        return [d] if d else []
    if entity_type == "project":
        p = db.get(models.Project, entity_id)
        return [p.direction] if p and p.direction else []
    if entity_type == "task":
        t = db.get(models.Task, entity_id)
        return [d for d in t.directions if d.deleted_at is None] if t else []
    return []


def auto_org(db: Session, entity_type: str, entity_id: int) -> list[models.Direction]:
    """Перевести в «Организацию» направления, которых коснулся новый доступ или поручение.

    Трогаем только непришпиленные (`space_pinned == False`) и только те, что ещё в личном.
    Возвращаем те, что действительно переехали — фронт показывает тост
    «Направление N перешло в Организацию · Отменить» (кнопка шлёт обратный перенос,
    он же выставит `space_pinned`, и направление больше не будет переезжать само).

    Коммит — на вызывающей стороне, вместе с самим действием.
    """
    moved: list[models.Direction] = []
    for d in directions_touched(db, entity_type, entity_id):
        if d.space != PERSONAL or d.space_pinned:
            continue
        d.space = ORG
        moved.append(d)
    return moved


def access_preview(db: Session, direction: models.Direction) -> list[dict]:
    """Кому открыто направление — само, его проекты и его задачи.

    Нужно для окна «Перенести в Личное»: владелец должен видеть, кто продолжит это
    видеть, если доступ оставить. Одна строка на человека, право — сильнейшее из его шар.
    """
    project_ids = [p.id for p in direction.projects]
    task_ids = [t.id for t in direction.tasks]
    rows = db.scalars(
        select(models.Share).where(
            (models.Share.entity_type == "direction") & (models.Share.entity_id == direction.id)
            | ((models.Share.entity_type == "project") & models.Share.entity_id.in_(project_ids or [-1]))
            | ((models.Share.entity_type == "task") & models.Share.entity_id.in_(task_ids or [-1]))
        )
    ).all()
    best: dict[int, dict] = {}
    for s in rows:
        cur = best.get(s.user_id)
        if cur is None or (cur["permission"] == "view" and s.permission == "edit"):
            best[s.user_id] = {
                "user_id": s.user_id,
                "name": s.user.name if s.user else "",
                "email": s.user.email if s.user else "",
                "permission": s.permission,
                "via": s.entity_type,
            }
    return sorted(best.values(), key=lambda r: r["name"].lower())


def revoke_all(db: Session, direction: models.Direction) -> int:
    """Снять весь доступ к направлению, его проектам и задачам. Возвращает число снятых шар."""
    project_ids = [p.id for p in direction.projects]
    task_ids = [t.id for t in direction.tasks]
    rows = db.scalars(
        select(models.Share).where(
            (models.Share.entity_type == "direction") & (models.Share.entity_id == direction.id)
            | ((models.Share.entity_type == "project") & models.Share.entity_id.in_(project_ids or [-1]))
            | ((models.Share.entity_type == "task") & models.Share.entity_id.in_(task_ids or [-1]))
        )
    ).all()
    for s in rows:
        db.delete(s)
    return len(rows)
