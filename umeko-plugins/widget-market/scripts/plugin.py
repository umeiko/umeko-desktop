from umeko_plugin_sdk import Plugin


def create_plugin(context):
    # The page uses asynchronous Widget Host calls only when opened.
    # Creating this plugin starts no network, subprocess or background task.
    return Plugin(context)
