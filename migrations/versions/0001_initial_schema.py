"""Initial TUQS schema: user_quotas and token_ledger (Stories 8.1-8.3).

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_quotas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("token_limit", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "date", name="uq_user_date"),
        sa.CheckConstraint("tokens_used >= 0", name="ck_user_quotas_tokens_used_nonneg"),
        sa.CheckConstraint("token_limit > 0", name="ck_user_quotas_token_limit_positive"),
    )
    op.create_table(
        "token_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("prompt_tokens >= 0", name="ck_token_ledger_prompt_nonneg"),
        sa.CheckConstraint("completion_tokens >= 0", name="ck_token_ledger_completion_nonneg"),
        sa.CheckConstraint(
            "total_tokens = prompt_tokens + completion_tokens", name="ck_token_ledger_total_sum"
        ),
        sa.CheckConstraint("total_tokens > 0", name="ck_token_ledger_total_positive"),
    )
    op.create_index("ix_token_ledger_user_ts", "token_ledger", ["user_id", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_token_ledger_user_ts", table_name="token_ledger")
    op.drop_table("token_ledger")
    op.drop_table("user_quotas")
