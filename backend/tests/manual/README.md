# 手工测试脚本

这个目录存放一次性验证、结构巡检和联调用的手工脚本，不属于默认 pytest 自动化测试集合。

约定：
- 从 backend 根目录执行，例如 python tests/manual/test_all_skills.py。
- 脚本内部已经按文件位置自动定位 backend 根目录，不依赖当前工作目录。
- 新增临时验证脚本优先放在这里，不再直接落到 backend 根目录。