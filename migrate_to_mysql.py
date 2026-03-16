# -*- coding: utf-8 -*-
"""
将 SQLite 数据迁移到 MySQL。
用法：python migrate_to_mysql.py
"""
import json
import sqlite3
from pathlib import Path

import pymysql

SQLITE_PATH = Path(__file__).resolve().parent / "data" / "aiword.db"

MYSQL_HOST = "10.26.1.221"
MYSQL_PORT = 13306
MYSQL_USER = "root"
MYSQL_PASSWORD = "mysql170921"
MYSQL_DB = "aiword"

TABLES = [
    "users",
    "task_type_configs",
    "completion_status_configs",
    "audit_status_configs",
    "notify_template_configs",
    "app_configs",
    "module_cascade_reminders",
    "upload_records",
    "generate_records",
    "generation_summary",
]


def get_sqlite_rows(sqlite_conn, table):
    cur = sqlite_conn.execute(f"SELECT * FROM [{table}]")
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    return columns, rows


def migrate():
    if not SQLITE_PATH.exists():
        print(f"SQLite 文件不存在: {SQLITE_PATH}")
        print("无数据需要迁移，MySQL 表将在应用启动时自动创建。")
        return

    print(f"SQLite: {SQLITE_PATH}")
    print(f"MySQL:  {MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}")
    print()

    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))

    existing_tables = {
        row[0]
        for row in sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    mysql_conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
    )
    mysql_cur = mysql_conn.cursor()

    mysql_cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    mysql_cur.execute(f"USE `{MYSQL_DB}`")
    mysql_conn.commit()

    print("开始迁移数据表...")
    total_rows = 0

    for table in TABLES:
        if table not in existing_tables:
            print(f"  跳过 {table} (SQLite 中不存在)")
            continue

        columns, rows = get_sqlite_rows(sqlite_conn, table)
        if not rows:
            print(f"  跳过 {table} (无数据)")
            continue

        mysql_cur.execute(f"SHOW TABLES LIKE '{table}'")
        if not mysql_cur.fetchone():
            print(f"  跳过 {table} (MySQL 中表不存在，请先启动应用创建表)")
            continue

        mysql_cur.execute(f"SELECT COUNT(*) FROM `{table}`")
        existing_count = mysql_cur.fetchone()[0]
        if existing_count > 0:
            print(f"  跳过 {table} (MySQL 中已有 {existing_count} 条数据)")
            continue

        mysql_cur.execute(f"DESCRIBE `{table}`")
        mysql_columns = {row[0] for row in mysql_cur.fetchall()}
        valid_columns = [c for c in columns if c in mysql_columns]
        if not valid_columns:
            print(f"  跳过 {table} (无匹配列)")
            continue

        col_indices = [columns.index(c) for c in valid_columns]
        placeholders = ", ".join(["%s"] * len(valid_columns))
        col_names = ", ".join(f"`{c}`" for c in valid_columns)
        insert_sql = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"

        batch = []
        for row in rows:
            values = []
            for i, ci in enumerate(col_indices):
                val = row[ci]
                if isinstance(val, bytes):
                    val = val.decode("utf-8", errors="replace")
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                values.append(val)
            batch.append(tuple(values))

        try:
            mysql_cur.executemany(insert_sql, batch)
            mysql_conn.commit()
            print(f"  {table}: 迁移 {len(batch)} 条数据")
            total_rows += len(batch)
        except Exception as e:
            mysql_conn.rollback()
            print(f"  {table}: 迁移失败 - {e}")

    sqlite_conn.close()
    mysql_cur.close()
    mysql_conn.close()

    print(f"\n迁移完成！共迁移 {total_rows} 条数据。")
    print("现在可以启动应用连接 MySQL 了。")


if __name__ == "__main__":
    migrate()
