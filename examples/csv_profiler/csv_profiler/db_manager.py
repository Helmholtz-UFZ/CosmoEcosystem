"""The CSV profiler's own concrete ``jobs`` table.

Demonstrates the persistence seam every consuming app uses: the framework
supplies the intersection columns via ``JobColumns`` and the machinery via
``DbManager``, and the app declares its own concrete class on the shared
``Base``. See docs/conventions/database_schema.md.
"""

from sqlalchemy import JSON, Column, String

from cosmo_ecosystem.db_manager import Base, JobColumns


class JobTable(JobColumns, Base):
    """Concrete ``jobs`` table for the CSV profiler.

    ``input_data`` and ``logs`` are not in the framework's intersection
    (cosmonaut has neither), so they are mapped here alongside the six
    columns inherited from ``JobColumns``.
    """

    __tablename__ = "jobs"

    input_data = Column(JSON)
    logs = Column(String)
