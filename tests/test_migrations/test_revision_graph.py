from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_history_has_one_resolvable_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    heads = script.get_heads()

    assert len(heads) == 1
    assert script.get_revision(heads[0]) is not None
