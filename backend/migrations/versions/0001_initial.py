"""Initial durable processing schema. Metadata is frozen in this revision."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Explicit DDL generated from the initial metadata; independent of future model edits.
    from migrations.initial_schema import metadata

    metadata.create_all(op.get_bind())


def downgrade():
    from migrations.initial_schema import metadata

    metadata.drop_all(op.get_bind())
