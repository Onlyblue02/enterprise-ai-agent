"""企业业务数据库的白名单查询工具。"""

import json

from langchain_core.tools import tool

from database_service import DatabaseService


def build_business_tools(database: DatabaseService) -> list:
    @tool("query_sales_data")
    def query_sales_data(
        year: int,
        start_month: int = 1,
        end_month: int = 12,
        region: str = "",
    ) -> str:
        """查询指定年份、月份范围和区域的企业月度销售明细。

        Args:
            year: 四位年份，例如 2026。
            start_month: 开始月份，范围 1 到 12。
            end_month: 结束月份，范围 1 到 12。
            region: 可选区域，例如华东、华南、华北；查询全部区域时传空字符串。
        """
        rows = database.query_sales(year, start_month, end_month, region)
        if not rows:
            return "没有查询到符合条件的销售数据。"
        return json.dumps(rows, ensure_ascii=False, indent=2)

    @tool("query_sales_summary")
    def query_sales_summary(
        year: int,
        start_month: int = 1,
        end_month: int = 12,
    ) -> str:
        """按区域汇总指定年份和月份范围的销售额，并按销售额从高到低排列。"""
        rows = database.sales_summary(year, start_month, end_month)
        if not rows:
            return "没有查询到符合条件的销售汇总数据。"
        return json.dumps(rows, ensure_ascii=False, indent=2)

    @tool("query_project_status")
    def query_project_status(project_name: str) -> str:
        """根据准确项目名称查询负责部门、负责人、状态、进度和更新时间。"""
        project = database.query_project(project_name)
        if not project:
            return f"没有找到项目：{project_name}。"
        return json.dumps(project, ensure_ascii=False, indent=2)

    return [query_sales_data, query_sales_summary, query_project_status]
