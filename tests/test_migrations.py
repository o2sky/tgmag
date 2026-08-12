from pathlib import Path


def test_initial_migration_matches_incremental_history() -> None:
    initial = Path("alembic/versions/0001_initial.py").read_text(encoding="utf-8")
    second = Path("alembic/versions/0002_service_message_full_text.py").read_text(encoding="utf-8")
    third = Path("alembic/versions/0003_service_source_unique.py").read_text(encoding="utf-8")
    fifth = Path("alembic/versions/0005_login_email_protection.py").read_text(encoding="utf-8")
    sixth = Path("alembic/versions/0006_login_email_retry_count.py").read_text(encoding="utf-8")
    seventh = Path("alembic/versions/0007_login_email_aggregation_window.py").read_text(
        encoding="utf-8"
    )
    eighth = Path("alembic/versions/0008_account_login_email_window.py").read_text(encoding="utf-8")
    ninth = Path("alembic/versions/0009_temp_mail_messages.py").read_text(encoding="utf-8")
    assert 'sa.Column("text", sa.Text()' not in initial
    assert "uq_service_account_message" in initial
    assert 'op.add_column("service_messages"' in second
    assert 'op.drop_constraint("uq_service_account_message"' in third
    assert '"login_email_whitelist"' in fifth
    assert '"login_email_protection_events"' in fifth
    assert '"login_email_encrypted"' in fifth
    assert '"attempt_count"' in sixth
    assert '"window_ends_at"' in seventh
    assert '"alert_count"' in seventh
    assert '"parent_event_id"' in seventh
    assert '"login_email_window_hours"' in eighth
    assert 'server_default="0"' in eighth
    assert "login_email_window_hours >= 0 AND login_email_window_hours <= 720" in eighth
    assert '"temp_mail_messages"' in ninth
    assert 'sa.PrimaryKeyConstraint("id", "to"' in ninth
    assert '"received_at"' in ninth
