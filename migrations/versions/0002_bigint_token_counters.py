"""Widen token counters to BIGINT (PRD FR-5, AD-3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUOTA_COLUMNS = ("tokens_used", "token_limit")
LEDGER_COLUMNS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _retype(table: str, columns, old, new) -> None:
    # batch mode recreates the table on SQLite, which cannot ALTER COLUMN TYPE
    with op.batch_alter_table(table) as batch:
        for column in columns:
            batch.alter_column(column, existing_type=old, type_=new, existing_nullable=False)


def upgrade() -> None:
    _retype("user_quotas", QUOTA_COLUMNS, sa.Integer(), sa.BigInteger())
    _retype("token_ledger", LEDGER_COLUMNS, sa.Integer(), sa.BigInteger())


def downgrade() -> None:
    _retype("token_ledger", LEDGER_COLUMNS, sa.BigInteger(), sa.Integer())
    _retype("user_quotas", QUOTA_COLUMNS, sa.BigInteger(), sa.Integer())
