from umeko_provider_sdk import Provider


class EchoProvider(Provider):
    def authenticate(self, credentials):
        self.context.secrets.set("session", {"name": credentials["username"]})
        return {"label": credentials["username"]}

    def list_models(self, refresh=False):
        return [{"id": "local-echo", "contextWindow": 8192, "vision": False}]

    def events(self, model, messages, tools, max_tokens, parameters):
        content = messages[-1].get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
        yield {"model": model, "choices": [{"index": 0, "delta": {"content": self.context.config["prefix"] + content}, "finish_reason": None}]}
        yield {"model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def create_provider(context):
    return EchoProvider(context)
