"""archivos: proposito etiqueta

Revision ID: e865ca134acc
Revises: 9765b6bfd4c2
Create Date: 2026-10-20 16:03:56.302566

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e865ca134acc'
down_revision = '9765b6bfd4c2'
branch_labels = None
depends_on = None


NEW = "('producto', 'conteo', 'importacion', 'etiqueta')"
OLD = "('producto', 'conteo', 'importacion')"


def upgrade():
    with op.batch_alter_table('stored_files', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('ck_stored_files_purpose_valid'), type_='check')
        batch_op.create_check_constraint('purpose_valid', f"purpose IN {NEW}")


def downgrade():
    op.execute("DELETE FROM stored_files WHERE purpose = 'etiqueta'")
    with op.batch_alter_table('stored_files', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('ck_stored_files_purpose_valid'), type_='check')
        batch_op.create_check_constraint('purpose_valid', f"purpose IN {OLD}")
