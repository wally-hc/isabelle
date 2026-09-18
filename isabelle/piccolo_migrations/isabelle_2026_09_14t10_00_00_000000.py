from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Varchar
from piccolo.columns.indexes import IndexMethod


ID = "2026-09-14T10:00:00:000000"
VERSION = "1.28.0"
DESCRIPTION = "Group the dates of a repeating event into one series"


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="isabelle", description=DESCRIPTION
    )

    manager.add_column(
        table_class_name="Event",
        tablename="event",
        column_name="SeriesID",
        db_column_name="SeriesID",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 36,
            "default": "",
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": True,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    return manager
