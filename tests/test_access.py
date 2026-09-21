from __future__ import annotations

from bot.access import (
    format_person_label,
    is_main_admin,
    listed_telegram_ids,
    merge_recipient_ids,
    resolve_main_admin_id,
)


def test_main_admin_defaults_to_first_env_admin():
    assert resolve_main_admin_id([11, 22], None) == 11
    assert is_main_admin(11, [11, 22], None) is True
    assert is_main_admin(22, [11, 22], None) is False


def test_main_admin_override():
    assert resolve_main_admin_id([11, 22], 22) == 22
    assert is_main_admin(22, [11, 22], 22) is True
    assert is_main_admin(11, [11, 22], 22) is False


def test_merge_recipients_unique_and_skips_sender():
    ids = merge_recipient_ids(
        env_admins=[11, 22],
        db_user_ids=[22, 33, 44],
        sender_id=11,
    )
    assert ids == [22, 33, 44]


def test_format_person_label_fio_and_username():
    assert format_person_label(
        first_name="Иван", last_name="Петров", username="ivan", telegram_id=11,
    ) == "Иван Петров · @ivan"


def test_format_person_label_falls_back():
    assert format_person_label(
        first_name=None, last_name=None, username="maria", telegram_id=22,
    ) == "@maria"
    assert format_person_label(
        first_name="Пётр", last_name=None, username=None, telegram_id=33,
    ) == "Пётр"
    assert format_person_label(
        first_name=None, last_name=None, username=None, telegram_id=44,
    ) == "44"


def test_listed_telegram_ids_env_then_db_without_dupes():
    assert listed_telegram_ids([11, 22], [22, 33]) == [11, 22, 33]
