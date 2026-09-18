from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Text, Timestamp, Varchar
from piccolo.columns.indexes import IndexMethod


ID = "2026-09-16T10:00:00:000000"
VERSION = "1.28.0"
DESCRIPTION = "The repeating rule behind a series, and the timezone it runs in"


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="isabelle", description=DESCRIPTION
    )

    manager.add_table(
        class_name="Series", tablename="series", schema=None, columns=None
    )

    manager.add_column(
        table_class_name="Series",
        tablename="series",
        column_name="SeriesID",
        db_column_name="SeriesID",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 36,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": True,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    for name in ("Rule",):
        manager.add_column(
            table_class_name="Series",
            tablename="series",
            column_name=name,
            db_column_name=name,
            column_class_name="Text",
            column_class=Text,
            params={
                "default": "",
                "null": False,
                "primary_key": False,
                "unique": False,
                "index": False,
                "index_method": IndexMethod.btree,
                "choices": None,
                "db_column_name": None,
                "secret": False,
            },
            schema=None,
        )

    manager.add_column(
        table_class_name="Series",
        tablename="series",
        column_name="Timezone",
        db_column_name="Timezone",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 64,
            "default": "UTC",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="Series",
        tablename="series",
        column_name="LeaderSlackID",
        db_column_name="LeaderSlackID",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 32,
            "default": "",
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="Series",
        tablename="series",
        column_name="CreatedAt",
        db_column_name="CreatedAt",
        column_class_name="Timestamp",
        column_class=Timestamp,
        params={
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    return manager
