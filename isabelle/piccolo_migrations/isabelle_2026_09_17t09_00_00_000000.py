from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import SmallInt, Text, Timestamp, UUID, Varchar
from piccolo.columns.indexes import IndexMethod


ID = "2026-09-17T09:00:00:000000"
VERSION = "1.28.0"
DESCRIPTION = "An append-only record of what reviewers did"


def _params(**overrides):
    base = {
        "null": True,
        "primary_key": False,
        "unique": False,
        "index": False,
        "index_method": IndexMethod.btree,
        "choices": None,
        "db_column_name": None,
        "secret": False,
    }
    base.update(overrides)
    return base


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="isabelle", description=DESCRIPTION
    )

    manager.add_table(
        class_name="AuditEntry", tablename="audit_entry", schema=None, columns=None
    )

    manager.add_column(
        table_class_name="AuditEntry",
        tablename="audit_entry",
        column_name="id",
        db_column_name="id",
        column_class_name="UUID",
        column_class=UUID,
        params=_params(null=False, primary_key=True, unique=True, default=None),
        schema=None,
    )

    manager.add_column(
        table_class_name="AuditEntry",
        tablename="audit_entry",
        column_name="At",
        db_column_name="At",
        column_class_name="Timestamp",
        column_class=Timestamp,
        params=_params(default=None, index=True),
        schema=None,
    )

    for name, length in (
        ("ActorSlackID", 32),
        ("Action", 32),
        ("EventID", 36),
        ("SeriesID", 36),
        ("Scope", 16),
    ):
        manager.add_column(
            table_class_name="AuditEntry",
            tablename="audit_entry",
            column_name=name,
            db_column_name=name,
            column_class_name="Varchar",
            column_class=Varchar,
            params=_params(length=length, default=""),
            schema=None,
        )

    for name in ("EventTitle", "Reason"):
        manager.add_column(
            table_class_name="AuditEntry",
            tablename="audit_entry",
            column_name=name,
            db_column_name=name,
            column_class_name="Text",
            column_class=Text,
            params=_params(default=""),
            schema=None,
        )

    manager.add_column(
        table_class_name="AuditEntry",
        tablename="audit_entry",
        column_name="Affected",
        db_column_name="Affected",
        column_class_name="SmallInt",
        column_class=SmallInt,
        params=_params(default=1, null=False),
        schema=None,
    )

    return manager
