from umeko_plugin_sdk import Plugin


def create_plugin(context):
    # The page uses only the scoped asynchronous host interface.
    return Plugin(context)
