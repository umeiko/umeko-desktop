"""Fetch optional provider model limits without changing the user's mappings."""
import json
import urllib.error
import urllib.request

from .gateway import NoRedirect, validate_base_url
from .model_context import provider_context_window
from umeko_provider_sdk.network import proxy_handler


def fetch_model_windows(provider):
    base = validate_base_url(provider["baseUrl"])
    headers = {"Accept": "application/json", "User-Agent": "Umeko-Desktop"}
    if provider["api"] == "anthropic":
        url = base + ("/models" if base.endswith("/v1") else "/v1/models")
        headers.update({"x-api-key": provider["key"], "anthropic-version": "2023-06-01"})
    else:
        url = base + "/models"
        headers["Authorization"] = "Bearer " + provider["key"]
    opener = urllib.request.build_opener(proxy_handler(provider.get("proxy")), NoRedirect())
    windows = {}
    # Anthropic and compatible services may paginate their model catalog.
    for _ in range(100):
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=15) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise ValueError(f"模型列表返回 HTTP {code} / Model list returned HTTP {code}") from None
        rows = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("供应商模型列表格式无效 / Invalid provider model list")
        for row in rows:
            if isinstance(row, dict):
                name = row.get("id") or row.get("name")
                if isinstance(name, str) and name:
                    windows[name] = provider_context_window(row)
        if not isinstance(payload, dict) or not payload.get("has_more"):
            return windows
        last = payload.get("last_id")
        if not isinstance(last, str) or not last:
            raise ValueError("模型列表缺少分页游标 / Model list has no pagination cursor")
        from urllib.parse import urlencode
        url = base + ("/models" if base.endswith("/v1") or provider["api"] != "anthropic" else "/v1/models") + "?" + urlencode({"after_id": last})
    raise ValueError("供应商模型列表页数过多 / Too many provider model pages")
