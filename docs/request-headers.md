# Custom model request headers

Open **Settings → Agent → Umeko Desktop → Custom requests**.
The entry opens a separate settings page. Use the **Umeko Desktop** back button
to return to the overview; unsaved header edits remain available when you reopen it.

- Edit a field's name or value, then select **Save headers**. For example, change
  `User-Agent` to `My-Client/1.0`.
- Select **Add field** to send an additional header, such as `X-Project: my-project`.
- Turn off a field to omit it from the request; delete custom fields with the trash button.
- **Restore defaults** immediately restores the original header configuration.
  **Discard changes** only discards unsaved edits.

The `{{apiKey}}` placeholder uses the selected provider's key at request time.
OpenAI's `Authorization` and Anthropic's `x-api-key` / `anthropic-version` rows
only apply to their respective protocols. Other rows apply to all built-in
OpenAI and Anthropic requests, including Responses, reasoning probes, model
metadata discovery, and image, speech and video generation.

Changes apply to subsequent requests without restarting active conversations.
They also apply when a model is called through Umeko's API proxy. They do not
alter the proxy's incoming authentication, plugin-owned requests, external dsh,
updates, or external media downloads.

Settings are local to the current Umeko profile. Header values may contain
credentials: the agent's `settings.get` result redacts them, and local failure
reports redact outgoing header values and echoed values. Provider keys remain
in the existing credential store; placeholders do not duplicate those keys in
the header settings.

Names are case-insensitive and must be valid HTTP field names. Each protocol
can send a name only once. Values must fit HTTP Latin-1 and contain no control
characters or newlines. Transport framing fields such as `Host`, `Content-Length`
and `Transfer-Encoding` remain managed by the network library. There can be at
most 32 rows (including defaults), with names up to 128 and values up to 4096
characters.
