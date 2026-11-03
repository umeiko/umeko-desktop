"""Presentation names for the existing runtime classifier's seven categories.

Grants live only in Store.sessionMeta, alongside the conversation's other UI
metadata. The runtime classifier remains the authority on dangerous operations.
"""

CATEGORIES = {
    1: "递归删除",
    2: "磁盘或分区修改",
    3: "关机、重启或注销",
    4: "系统配置修改",
    5: "受保护路径权限修改",
    6: "强制推送主分支",
    7: "系统目录写入",
}


def clean_grants(value):
    return sorted({category for category in value if type(category) is int and category in CATEGORIES}) if isinstance(value, list) else []
