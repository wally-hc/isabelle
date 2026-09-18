from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Array, Text
from piccolo.columns.indexes import IndexMethod


ID = "2026-09-16T21:00:00:000000"
VERSION = "1.28.0"
DESCRIPTION = "People following every date of a series"


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="isabelle", description=DESCRIPTION
    )

    manager.add_column(
        table_class_name="Series",
        tablename="series",
        column_name="Followers",
        db_column_name="Followers",
        column_class_name="Array",
        column_class=Array,
        params={
            "base_column": Text(),
            "default": list,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": True,
        },
        schema=None,
    )

    return manager
