"""本地只读业务查询服务，使用 SQLite 模拟企业数据。"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import config_data as config


class DatabaseService:
    """初始化演示数据，并暴露固定的只读业务查询。"""

    def __init__(self, database_path: str | Path | None = None):
        self.database_path = Path(database_path or config.enterprise_database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monthly_sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    region TEXT NOT NULL,
                    department TEXT NOT NULL,
                    amount REAL NOT NULL,
                    UNIQUE(year, month, region, department)
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL UNIQUE,
                    department TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            sales_count = connection.execute(
                "SELECT COUNT(*) FROM monthly_sales"
            ).fetchone()[0]
            if sales_count == 0:
                connection.executemany(
                    """
                    INSERT INTO monthly_sales
                        (year, month, region, department, amount)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    self._demo_sales(),
                )

            project_count = connection.execute(
                "SELECT COUNT(*) FROM projects"
            ).fetchone()[0]
            if project_count == 0:
                connection.executemany(
                    """
                    INSERT INTO projects
                        (project_name, department, owner, status, progress, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("企业知识助手", "技术部", "张伟", "开发中", 72.0, "2026-07-10"),
                        ("客户数据平台", "数据部", "李娜", "测试中", 85.0, "2026-07-08"),
                        ("销售预测系统", "销售部", "王强", "规划中", 25.0, "2026-07-06"),
                    ],
                )

    @staticmethod
    def _demo_sales() -> list[tuple]:
        regions = {
            "华东": (120.0, "销售一部"),
            "华南": (105.0, "销售二部"),
            "华北": (98.0, "销售三部"),
        }
        rows = []
        for month in range(1, 7):
            for index, (region, (base, department)) in enumerate(regions.items()):
                amount = (base + month * 6 + index * 2) * 10000
                rows.append((2026, month, region, department, amount))
        return rows

    def query_sales(
        self,
        year: int,
        start_month: int = 1,
        end_month: int = 12,
        region: str = "",
    ) -> list[dict]:
        if not 1 <= start_month <= end_month <= 12:
            raise ValueError("月份范围必须满足 1 <= start_month <= end_month <= 12")

        sql = (
            "SELECT year, month, region, department, amount "
            "FROM monthly_sales WHERE year = ? AND month BETWEEN ? AND ?"
        )
        params: list = [year, start_month, end_month]
        if region:
            sql += " AND region = ?"
            params.append(region)
        sql += " ORDER BY month, region"

        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def sales_summary(self, year: int, start_month: int = 1, end_month: int = 12) -> list[dict]:
        if not 1 <= start_month <= end_month <= 12:
            raise ValueError("月份范围必须满足 1 <= start_month <= end_month <= 12")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT region, ROUND(SUM(amount), 2) AS total_amount
                FROM monthly_sales
                WHERE year = ? AND month BETWEEN ? AND ?
                GROUP BY region
                ORDER BY total_amount DESC
                """,
                (year, start_month, end_month),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_project(self, project_name: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT project_name, department, owner, status, progress, updated_at
                FROM projects WHERE project_name = ?
                """,
                (project_name,),
            ).fetchone()
        return dict(row) if row else None
