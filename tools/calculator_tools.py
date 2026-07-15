"""不执行任意代码的安全数值计算工具。"""

from langchain_core.tools import tool


def build_calculator_tools() -> list:
    @tool("calculate")
    def calculate(operation: str, a: float, b: float = 0.0) -> str:
        """执行两个数之间的安全计算。

        Args:
            operation: add、subtract、multiply、divide、percentage_change 或 ratio_percent。
            a: 第一个数；percentage_change 时表示当前值，ratio_percent 时表示部分值。
            b: 第二个数；percentage_change 时表示原值，ratio_percent 时表示总值。
        """
        operations = {
            "add": lambda: a + b,
            "subtract": lambda: a - b,
            "multiply": lambda: a * b,
            "divide": lambda: a / b,
            "percentage_change": lambda: (a - b) / b * 100,
            "ratio_percent": lambda: a / b * 100,
        }
        if operation not in operations:
            return "不支持的操作。可用操作：" + "、".join(operations)
        if b == 0 and operation in {"divide", "percentage_change", "ratio_percent"}:
            return "计算失败：除数或基准值不能为 0。"
        result = operations[operation]()
        return f"计算结果：{result:.4f}"

    return [calculate]
