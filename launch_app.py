"""PyCharm 一键启动入口。"""

import sys

from streamlit.web.cli import main


if __name__ == "__main__":
    sys.argv = ["streamlit", "run", "app.py"]
    raise SystemExit(main())
