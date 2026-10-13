# -*- coding: utf-8 -*-
"""「员工沟通模板」输出质量校验命令行入口。

用法：
    python scripts/quality_check.py <交付物.md>     # 校验一份交付物
    python scripts/quality_check.py --package      # 校验本技能包自身
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import (check_output, check_package,  # noqa: E402
                     format_report, format_package_report)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        path = args[0]
        if not os.path.isfile(path):
            print("文件不存在：" + path)
            return 2
        with io.open(path, encoding="utf-8") as f:
            report = check_output(f.read())
        print(format_report(report))
        return 0 if report["passed"] else 1
    report = check_package()
    print(format_package_report(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
