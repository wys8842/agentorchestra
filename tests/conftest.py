"""pytest 共享配置"""
import os
import sys

# 确保能导入 symphony（开发模式）
# symphony 包位于 D:\proj\symphony（__init__.py 在此），
# 其父目录 D:\proj 需在 sys.path 中才能 import symphony
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_project_root))  # D:\proj
sys.path.insert(0, _project_root)  # D:\proj\symphony
