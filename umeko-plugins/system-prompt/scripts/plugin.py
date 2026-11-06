from umeko_plugin_sdk import Plugin


def create_plugin(context):
    # The built-in page uses the scoped asynchronous host interface only.
    return Plugin(context)
