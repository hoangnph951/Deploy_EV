from src.apps.api.bootstrap.config import get_settings
from src.packages.core.trips.infrastructure.sqlalchemy_repository import SqlAlchemyTripRepository


def main() -> None:
    settings = get_settings()
    repository = SqlAlchemyTripRepository(settings.database_url)
    repository.ensure_schema()
    print("F1-US1 schema applied and vehicle profile seeded.")


if __name__ == "__main__":
    main()
