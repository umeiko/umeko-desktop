from umeko_plugin_sdk import Plugin


def create_plugin(context):
    # All UI work uses the scoped asynchronous Widget Host API. No polling,
    # network requests, subprocesses or background task is started here.
    return Plugin(context)
