"""v1.2 — имена людей кириллицей ↔ латиницей.

Симптом: при первом входе имя берётся из Microsoft на латинице («Aidos Bekov»), а голосом Claude передаёт
«Айдос» → «Человек не найдено» или дубль в справочнике. Проверяем тем же симптомом через /mcp.
"""
import json

import pytest
from sqlalchemy import select

from app import models
from app.names import key, person_matches
from tests.conftest import ok


def rpc(client, u, tool, **args):
    r = client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                 "params": {"name": tool, "arguments": args}}), headers=u.mcp_h)
    assert r.status_code == 200, r.text[:200]
    res = r.json()["result"]
    return json.loads(res["content"][0]["text"]), bool(res.get("isError"))


def must_ok(client, u, tool, **args):
    d, err = rpc(client, u, tool, **args)
    assert not err, f"{tool}({args}) → {d}"
    return d


def person(db, name, email=None):
    p = models.Person(name=name, email=email); db.add(p); db.commit(); db.refresh(p)
    return p


# ── ключи ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cyr,lat", [
    ("Жанибек", "Zhanibek"), ("Жанибек", "Janibek"), ("Жанибек", "Dzhanibek"),
    ("Айдос", "Aidos"), ("Айдос", "Aydos"),
    ("Сергей", "Sergey"), ("Сергей", "Sergei"), ("Алексей", "Alexey"), ("Алексей", "Aleksei"),
    ("Евгений", "Yevgeniy"), ("Евгений", "Evgeny"), ("Юрий", "Yuri"), ("Юрий", "Iurii"), ("Яна", "Yana"),
    ("Нурлан", "Nurlan"), ("Аида", "Aida"), ("Абильханов", "Abilkhanov"), ("Мубинов", "Mubinov"),
    ("Ерлан", "Yerlan"), ("Ерлан", "Erlan"), ("Ержан", "Yerzhan"), ("Чингиз", "Chingiz"), ("Шынар", "Shynar"),
    ("Щербаков", "Shcherbakov"), ("Цой", "Tsoy"), ("Хасан", "Khasan"), ("Хасан", "Hasan"),
    ("Дмитрий", "Dmitry"), ("Дмитрий", "Dmitrii"), ("Ксения", "Kseniya"), ("Ксения", "Xenia"),
    ("Әсел", "Asel"), ("Қайрат", "Kairat"), ("Гүлнар", "Gulnar"), ("Ілияс", "Iliyas"),
])
def test_key_same_for_cyrillic_and_latin(cyr, lat):
    assert key(cyr) == key(lat), (key(cyr), key(lat))


@pytest.mark.parametrize("q,name", [("Айдар", "Aidos Bekov"), ("Аида", "Aidos Bekov"), ("Али", "Aliya Nurova"), ("Нурлан", "Nurbek Aliev"),
                                    ("Айдос Беков", "Aidos Nurov")])
def test_no_false_hits(q, name):
    assert not person_matches(q, name)


def test_word_order_and_email():
    assert person_matches("Беков Айдос", "Aidos Bekov")
    assert person_matches("Абильханов", "Nurlan", "n.abilkhanov@cis.kz")   # фамилия только в почте
    assert person_matches("Aidos", "Айдос Беков")                            # обратное направление
    assert not person_matches("", "Aidos")


# ── тем же симптомом: через MCP ───────────────────────────────────────────────

def test_delegate_cyrillic_to_latin_person(client, db, jack):
    person(db, "Aidos Bekov", "aidos@cis.kz")
    t = must_ok(client, jack, "create_task", title="Согласовать смету")["task"]
    d = must_ok(client, jack, "delegate_task", task=t["id"], person="Айдос")
    assert "Aidos Bekov" in json.dumps(d, ensure_ascii=False)
    assert db.scalar(select(models.Delegation)).person.name == "Aidos Bekov"
    assert db.scalar(select(models.Person.name).where(models.Person.name.like("%йдос%"))) is None, "создался дубль кириллицей"


def test_create_task_assign_latin_to_cyrillic_person(client, db, jack):
    person(db, "Нурлан Абильханов", "n.abilkhanov@cis.kz")
    d = must_ok(client, jack, "create_task", title="Заказать запчасти", assign_to="Nurlan")
    assert d["task"]["assignees"] == ["Нурлан Абильханов"] if "assignees" in d["task"] else True
    assert db.scalar(select(models.Delegation)).person.name == "Нурлан Абильханов"


def test_surname_from_email(client, db, jack):
    person(db, "Zhanibek M", "zh.mubinov@cis.kz")
    t = must_ok(client, jack, "create_task", title="Проверить ЛВД")["task"]
    must_ok(client, jack, "delegate_task", task=t["id"], person="Мубинов")
    assert db.scalar(select(models.Delegation)).person.name == "Zhanibek M"


def test_create_person_if_missing_does_not_duplicate(client, db, jack):
    person(db, "Aidos Bekov", "aidos@cis.kz")
    t = must_ok(client, jack, "create_task", title="Собрать отчёт")["task"]
    must_ok(client, jack, "delegate_task", task=t["id"], person="Айдос Беков", create_person_if_missing=True)
    assert db.scalar(select(models.Person).where(models.Person.name != "Aidos Bekov")) is None, "с флагом создался дубль"


def test_create_person_duplicate_by_transliteration_rejected(client, db, jack):
    person(db, "Aidos Bekov", "aidos@cis.kz")
    d, err = rpc(client, jack, "create_person", name="Айдос Беков")
    assert err and "Aidos Bekov" in d["error"], d
    d, err = rpc(client, jack, "create_person", name="Айдос")
    assert err and "Aidos Bekov" in d["error"], d


def test_ambiguous_lists_candidates(client, db, jack):
    person(db, "Aidos Bekov"); person(db, "Айдос Нуров")
    t = must_ok(client, jack, "create_task", title="Позвонить")["task"]
    d, err = rpc(client, jack, "delegate_task", task=t["id"], person="Айдос")
    assert err and "несколько совпадений" in d["error"] and "Aidos Bekov" in d["error"] and "Айдос Нуров" in d["error"], d


def test_unknown_person_lists_available(client, db, jack):
    person(db, "Aidos Bekov")
    t = must_ok(client, jack, "create_task", title="Позвонить")["task"]
    d, err = rpc(client, jack, "delegate_task", task=t["id"], person="Бауыржан")
    assert err and "не найдено" in d["error"] and "Aidos Bekov" in d["error"], d


def test_get_person_report_by_cyrillic(client, db, jack):
    person(db, "Aidos Bekov")
    d = must_ok(client, jack, "get_person_report", person="айдос")
    assert "Aidos Bekov" in json.dumps(d, ensure_ascii=False)
