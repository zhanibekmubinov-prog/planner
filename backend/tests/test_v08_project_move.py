"""v0.8: перенос проекта в другое направление — move / copy, access-preview, grant_access_user_ids, В5 (403 для чужого направления).

Спецификация — /root/review/CONTRACT.md («Перенос проекта»).
"""
from sqlalchemy import select

from app import models
from tests.conftest import NUR_EMAIL, AIDA_EMAIL, count, ok


def _body(p: dict, **kw) -> dict:
    b = {k: p[k] for k in ("direction_id", "name", "description", "goal", "color", "status")}
    b.update(kw)
    return b


def _setup(api, jack, nur):
    """D1 (Нурлану edit, Аиде view) → P (Аиде — прямая шара edit) → T; D2 — второе направление Джека."""
    d1 = api.direction(jack, "Д1"); d2 = api.direction(jack, "Д2")
    p = api.project(jack, d1["id"], "П")
    t = api.task(jack, "в П", project_id=p["id"])
    api.share(jack, "direction", d1["id"], NUR_EMAIL, "edit")
    api.share(jack, "direction", d1["id"], AIDA_EMAIL, "view")
    return d1, d2, p, t


def test_move_replaces_direction_on_tasks(client, api, jack, nur):
    d1, d2, p, t = _setup(api, jack, nur)
    t_extra = api.task(jack, "в П и ещё где-то", project_id=p["id"])
    after = ok(client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d2["id"], move_mode="move"), headers=jack.h))
    assert after["direction_id"] == d2["id"] and after["access"] == "owner"
    for x in (t, t_extra):
        assert [d["id"] for d in api.get_task(jack, x["id"])["directions"]] == [d2["id"]], "после move задача должна остаться только в Д2"
    assert ok(client.get(f"/api/tasks?direction_id={d1['id']}", headers=jack.h)) == []
    assert [x["id"] for x in ok(client.get(f"/api/projects?direction_id={d2['id']}", headers=jack.h))] == [p["id"]]
    # Нурлан (edit на Д1) проект и задачу больше не видит — доступ через старое направление не переносится автоматически
    assert client.get(f"/api/projects/{p['id']}", headers=nur.h).status_code == 404
    assert client.get(f"/api/tasks/{t['id']}", headers=nur.h).status_code == 404


def test_copy_keeps_both_directions(client, api, jack, nur):
    d1, d2, p, t = _setup(api, jack, nur)
    ok(client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d2["id"], move_mode="copy"), headers=jack.h))
    assert sorted(d["id"] for d in api.get_task(jack, t["id"])["directions"]) == sorted([d1["id"], d2["id"]])
    # Нурлан всё ещё видит задачу через Д1, а проект — как via/через задачу
    assert ok(client.get(f"/api/tasks/{t['id']}", headers=nur.h))["access"] == "edit"


def test_default_mode_is_move(client, api, jack, nur):
    d1, d2, p, t = _setup(api, jack, nur)
    ok(client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d2["id"]), headers=jack.h))
    assert [d["id"] for d in api.get_task(jack, t["id"])["directions"]] == [d2["id"]]


def test_access_preview(client, api, db, jack, nur, aida):
    d1, d2, p, t = _setup(api, jack, nur)
    api.share(jack, "project", p["id"], AIDA_EMAIL, "edit")   # у Аиды прямая шара на проект — доступ сохранит; право сильнейшее (edit)
    rows = ok(client.get(f"/api/projects/{p['id']}/access-preview?direction_id={d2['id']}", headers=jack.h))
    by_email = {r["user"]["email"]: r for r in rows}
    assert set(by_email) == {NUR_EMAIL, AIDA_EMAIL}, rows
    assert by_email[NUR_EMAIL]["permission"] == "edit" and by_email[NUR_EMAIL]["keeps_access"] is False
    assert by_email[AIDA_EMAIL]["permission"] == "edit" and by_email[AIDA_EMAIL]["keeps_access"] is True
    # если Нурлану открыть Д2 — доступ сохранится и без прямой шары
    api.share(jack, "direction", d2["id"], NUR_EMAIL, "view")
    rows = ok(client.get(f"/api/projects/{p['id']}/access-preview?direction_id={d2['id']}", headers=jack.h))
    assert {r["user"]["email"]: r["keeps_access"] for r in rows}[NUR_EMAIL] is True
    assert client.get(f"/api/projects/{p['id']}/access-preview?direction_id=99999", headers=jack.h).status_code == 404
    assert client.get(f"/api/projects/{p['id']}/access-preview?direction_id={d2['id']}", headers=aida.h).status_code == 200  # edit на проект — можно
    assert client.get(f"/api/projects/{p['id']}/access-preview?direction_id={d2['id']}", headers=nur.h).status_code == 200


def test_grant_access_user_ids_creates_project_shares(client, api, db, jack, nur, aida):
    d1, d2, p, t = _setup(api, jack, nur)
    ok(client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d2["id"], move_mode="move", grant_access_user_ids=[nur.id, jack.id, 99999]), headers=jack.h))
    shares = db.execute(select(models.Share.entity_type, models.Share.entity_id, models.Share.user_id, models.Share.permission)
                        .where(models.Share.entity_type == "project")).all()
    assert shares == [("project", p["id"], nur.id, "edit")], f"ожидалась одна шара на проект с прежним правом edit: {shares}"
    assert ok(client.get(f"/api/projects/{p['id']}", headers=nur.h))["access"] == "edit"
    assert ok(client.get(f"/api/tasks/{t['id']}", headers=nur.h))["access"] == "edit"
    assert client.get(f"/api/projects/{p['id']}", headers=aida.h).status_code == 404   # Аиду не выбрали — доступ потерян
    # повторный перенос с тем же списком — шара не дублируется
    ok(client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d1["id"], grant_access_user_ids=[nur.id]), headers=jack.h))
    assert count(db, models.Share, models.Share.entity_type == "project", models.Share.user_id == nur.id) == 1


def test_editor_cannot_move_to_foreign_direction(client, api, jack, nur):
    """В5. Редактор направления переносит проект владельца в своё направление → 403 и ничего не меняется."""
    d1, d2, p, t = _setup(api, jack, nur)
    dn = api.direction(nur, "Личное (Nur)")
    r = client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=dn["id"]), headers=nur.h)
    assert r.status_code == 403, r.text
    assert ok(client.get(f"/api/projects/{p['id']}", headers=jack.h))["direction_id"] == d1["id"]
    assert [d["id"] for d in api.get_task(jack, t["id"])["directions"]] == [d1["id"]]
    # а в направление владельца, к которому у редактора тоже есть edit, — можно
    api.share(jack, "direction", d2["id"], NUR_EMAIL, "edit")
    after = ok(client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d2["id"]), headers=nur.h))
    assert after["direction_id"] == d2["id"] and after["owner"]["email"] == "jack@cis.kz"
    # редактор не видит чужое направление владельца → 404, проект остаётся
    d_private = api.direction(jack, "Приватное")
    assert client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d_private["id"]), headers=nur.h).status_code == 404


def test_owner_can_move_into_direction_shared_to_him(client, api, jack, nur):
    """Владелец проекта переносит его в направление коллеги, открытое ему на edit — разрешено; на view — 403."""
    d1, d2, p, t = _setup(api, jack, nur)
    dn = api.direction(nur, "Направление Нурлана")
    api.share(nur, "direction", dn["id"], "jack@cis.kz", "view")
    assert client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=dn["id"]), headers=jack.h).status_code == 403
    ok(client.post("/api/shares", json={"entity_type": "direction", "entity_id": dn["id"], "email": "jack@cis.kz", "permission": "edit"}, headers=nur.h), 201)
    after = ok(client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=dn["id"]), headers=jack.h))
    assert after["direction_id"] == dn["id"]
    assert [d["id"] for d in api.get_task(jack, t["id"])["directions"]] == [dn["id"]]


def test_move_to_direction_in_trash_is_404(client, api, jack, nur):
    d1, d2, p, t = _setup(api, jack, nur)
    ok(client.delete(f"/api/directions/{d2['id']}", headers=jack.h), 204)
    assert client.put(f"/api/projects/{p['id']}", json=_body(p, direction_id=d2["id"]), headers=jack.h).status_code == 404
