"""基于当前 SQLAlchemy 模型的一次性 Trade 建表脚本。

支持三种模式：
1. emit-sql: 导出当前模型对应的 PostgreSQL DDL。
2. verify: 在真实数据库事务内执行建表验证，并在结束后回滚。
3. apply: 真实创建缺失的 Trade 表。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Sequence

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import CreateEnumType
from sqlalchemy.schema import CreateIndex, CreateTable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.core.config import settings
from app.db.models import (
    Base,
    TradeHoldings,
    TradeListings,
    TradeOrders,
    TradeTransactionLog,
    TradeWallets,
    TradeYieldRuns,
)


TRADE_MODELS = (
    TradeListings,
    TradeOrders,
    TradeWallets,
    TradeHoldings,
    TradeYieldRuns,
    TradeTransactionLog,
)
TRADE_TABLES = tuple(model.__table__ for model in TRADE_MODELS)
TRADE_TABLE_NAMES = tuple(table.name for table in TRADE_TABLES)


def get_engine() -> sa.Engine:
    connect_args: dict[str, str] = {}
    if settings.DB_SSLMODE:
        connect_args["sslmode"] = settings.DB_SSLMODE
    return create_engine(settings.DATABASE_URL, connect_args=connect_args)


def iter_trade_enums() -> Iterable[sa.Enum]:
    seen: dict[str, sa.Enum] = {}
    for table in TRADE_TABLES:
        for column in table.columns:
            if isinstance(column.type, sa.Enum) and column.type.name:
                seen.setdefault(column.type.name, column.type)
    return seen.values()


def render_bootstrap_sql() -> str:
    dialect = postgresql.dialect()
    statements: list[str] = [
        "-- Trade bootstrap DDL generated from current SQLAlchemy models.",
        "-- Source of truth: backend/app/db/models.py",
        "BEGIN;",
        "",
    ]

    for enum_type in iter_trade_enums():
        statements.append(f"{CreateEnumType(enum_type).compile(dialect=dialect)};")
        statements.append("")

    for table in TRADE_TABLES:
        statements.append(f"{CreateTable(table).compile(dialect=dialect)};")
        statements.append("")

    for table in TRADE_TABLES:
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            statements.append(f"{CreateIndex(index).compile(dialect=dialect)};")
            statements.append("")

    statements.append("COMMIT;")
    statements.append("")
    return "\n".join(statements)


def ensure_users_table_exists(conn: sa.Connection) -> None:
    if not inspect(conn).has_table("users"):
        raise RuntimeError("当前数据库缺少 users 表，无法创建带外键的 trade_* 表")


def fetch_existing_trade_tables(conn: sa.Connection) -> list[str]:
    existing_tables = set(inspect(conn).get_table_names())
    return [name for name in TRADE_TABLE_NAMES if name in existing_tables]


def fetch_existing_trade_enums(conn: sa.Connection) -> list[str]:
    enum_names = [enum_type.name for enum_type in iter_trade_enums() if enum_type.name]
    if not enum_names:
        return []

    quoted = ", ".join(f"'{name}'" for name in enum_names)
    rows = conn.execute(
        text(f"SELECT typname FROM pg_type WHERE typname IN ({quoted}) ORDER BY typname")
    ).fetchall()
    return [row[0] for row in rows]


def verify_trade_schema() -> int:
    engine = get_engine()
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                ensure_users_table_exists(conn)
                existing_before = fetch_existing_trade_tables(conn)
                if existing_before:
                    raise RuntimeError(
                        "验证要求目标 trade_* 表当前不存在，避免污染真实环境；已存在: "
                        + ", ".join(existing_before)
                    )

                Base.metadata.create_all(conn, tables=TRADE_TABLES, checkfirst=True)

                tables_after_create = set(inspect(conn).get_table_names())
                missing_tables = [
                    name for name in TRADE_TABLE_NAMES if name not in tables_after_create
                ]
                if missing_tables:
                    raise RuntimeError(
                        "事务内建表验证失败，缺少表: " + ", ".join(missing_tables)
                    )

                existing_enums = fetch_existing_trade_enums(conn)
                expected_enums = sorted(
                    [enum_type.name for enum_type in iter_trade_enums() if enum_type.name]
                )
                if existing_enums != expected_enums:
                    raise RuntimeError(
                        "事务内枚举验证失败，期望: "
                        + ", ".join(expected_enums)
                        + "，实际: "
                        + ", ".join(existing_enums)
                    )

                print("verify_create_ok")
                print("tables", ",".join(TRADE_TABLE_NAMES))
                print("enums", ",".join(expected_enums))
            finally:
                transaction.rollback()

        with engine.connect() as conn:
            remaining_tables = fetch_existing_trade_tables(conn)
            remaining_enums = fetch_existing_trade_enums(conn)
            if remaining_tables or remaining_enums:
                raise RuntimeError(
                    "事务回滚后仍检测到残留对象，tables="
                    + ",".join(remaining_tables)
                    + " enums="
                    + ",".join(remaining_enums)
                )

        print("verify_rollback_ok")
        return 0
    finally:
        engine.dispose()


def apply_trade_schema() -> int:
    engine = get_engine()
    try:
        with engine.begin() as conn:
            ensure_users_table_exists(conn)
            Base.metadata.create_all(conn, tables=TRADE_TABLES, checkfirst=True)

        with engine.connect() as conn:
            created_tables = fetch_existing_trade_tables(conn)
            missing_tables = [name for name in TRADE_TABLE_NAMES if name not in created_tables]
            if missing_tables:
                raise RuntimeError(
                    "真实建表后仍缺少表: " + ", ".join(missing_tables)
                )

        print("apply_ok")
        print("tables", ",".join(TRADE_TABLE_NAMES))
        return 0
    finally:
        engine.dispose()


def emit_sql(output_path: Path | None) -> int:
    sql_text = render_bootstrap_sql()
    if output_path is None:
        print(sql_text)
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(sql_text, encoding="utf-8")
    print(f"sql_written {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trade 表一次性建表工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    emit_parser = subparsers.add_parser("emit-sql", help="导出 PostgreSQL 建表 SQL")
    emit_parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND_ROOT / "docs" / "deployment" / "trade_table_bootstrap.sql",
        help="输出 SQL 文件路径",
    )

    subparsers.add_parser("verify", help="事务内执行建表验证并回滚")
    subparsers.add_parser("apply", help="真实创建当前缺失的 Trade 表")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "emit-sql":
        return emit_sql(args.output)
    if args.command == "verify":
        return verify_trade_schema()
    if args.command == "apply":
        return apply_trade_schema()

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())