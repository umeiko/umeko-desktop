"""The official desktop-pet adapter is hosted by Umeko, not a Python worker.

Only this reserved built-in ID uses the host adapter. Imported Widgets cannot
request host access. All management still uses the ordinary widgets.* protocol.
"""
from umeko_plugin_sdk import Plugin, PluginError


def create_plugin(context):
    raise PluginError('桌面小宠物使用 Umeko 内置宿主，请从插件管理启用官方 Widget')
