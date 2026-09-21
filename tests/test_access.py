from __future__ import annotations

from bot.access import is_main_admin, merge_recipient_ids, resolve_main_admin_id


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
