"""exercise catalog table (MuscleWiki reference exercises)

Revision ID: 0002_catalog
Revises: 0001_initial
Create Date: 2026-06-01

Matches CatalogExerciseRow in app/db_models.py.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002_catalog"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_exercises",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("difficulty", sa.String(length=30), nullable=True),
        sa.Column("force", sa.String(length=30), nullable=True),
        sa.Column("grips", sa.String(length=50), nullable=True),
        sa.Column("primary_muscles", sa.JSON(), nullable=False),
        sa.Column("secondary_muscles", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("aka", sa.String(length=200), nullable=True),
        sa.Column("video_urls", sa.JSON(), nullable=False),
        sa.Column("youtube_url", sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_id", name="uq_catalog_source"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_catalog_exercises_source", "catalog_exercises", ["source"])
    op.create_index("ix_catalog_exercises_name", "catalog_exercises", ["name"])
    op.create_index("ix_catalog_exercises_slug", "catalog_exercises", ["slug"])
    op.create_index("ix_catalog_exercises_category", "catalog_exercises", ["category"])


def downgrade() -> None:
    op.drop_table("catalog_exercises")
