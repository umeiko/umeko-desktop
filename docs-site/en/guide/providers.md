# Accounts & models {#accounts-models}

## Three entry points {#three-entry-points}

In **Settings → Accounts and providers**, choose:

| Entry | Use it when |
| --- | --- |
| Common providers | A preset exists; enter its Key and an optional alias |
| API providers | You need to enter a protocol, Base URL and model configuration |
| Custom providers | A trusted provider ZIP implements sign-in and model access |

[![Three independent provider settings entries](/images/providers-en.png)](/images/providers-en.png)

*Common, API and custom providers have separate entry points. Use the plus button in Common providers to choose a brand.*

Common presets include Claude Code, Codex, Kimi Code, DeepSeek, GLM Coding Plan and MiniMax subscriptions. Where domestic and international sites are available, a dropdown changes the API address and Key application link together.

[![Common provider selection menu](/images/provider-choices-en.png)](/images/provider-choices-en.png)

1. Choose a brand, such as Kimi Code.
2. Follow Get API key to its console and enter the appropriate Key.
3. Optionally enter an alias, then select Add and use.

[![API Key and optional account alias form](/images/provider-key-en.png)](/images/provider-key-en.png)

::: tip Check the Key type
Common presets connect with an API Key. Claude Code / Codex presets take official API Keys. The Kimi Code preset takes a Kimi Code Key, which is a different Key from a Moonshot platform Key. Subscription Keys and pay-as-you-go endpoints each have their own scope. Check the selected site and your account permissions.
:::

## Multiple accounts and aliases {#multiple-accounts-and-aliases}

The first unnamed account appears as `Kimi`. An alias such as “Work” produces `Kimi(Work)`; a second unnamed account becomes `Kimi(2)`. You can add multiple accounts from one provider; when a name repeats, Umeko asks for another or numbers it automatically.

Adding an account saves its configuration without making a paid request. After saving, pick a model in the chat's model selector; the provider's permissions determine which models work.

## Network and model settings {#network-and-model-settings}

Use a provider card's small gear to choose the system proxy, a direct connection or a custom HTTP(S) proxy. Settings are saved per provider, separately from npm networking for Pi extensions.

Model settings allow context-length and vision overrides. Match them to the upstream model: these values tell Umeko how to use the model, and the upstream service determines what the model can do.

## Multimodal model options {#multimodal-models}

In **Settings → Accounts & Providers → Multimodal model options**, choose an existing account and model separately for image, speech and video generation. Select from the model catalogue or enter a raw upstream model ID. Generation reuses the account's credentials, proxy and CA settings, so no separate Key is needed. The upstream service needs to support the selected generation endpoint and parameters.

Images default to a count of `1`, with optional default size, quality and format. Speech requires a manually entered voice ID supported by the provider, with format `mp3` and speed `1` by default. Every call requests permission before sending the prompt or text, including in auto mode.

Video has optional duration (seconds) and resolution (for example `1280x720`) defaults; leave either blank for the provider default. `video_gen` creates an asynchronous provider job within one tool call. The tool header shows queued/generating state and the provider's progress percentage. The Stop button ends polling, discards the result and tries to delete the provider job; local cancellation takes effect either way. Restarting the app ends running video jobs.

Files are saved in the current chat workspace, adding a suffix if a name already exists. Images appear as thumbnails; audio and MP4 video appear as file cards that open in the default system app when clicked. Completed file cards are preserved in session history. The Agent receives file paths and text.

The video default follows the [OpenAI Videos protocol](https://developers.openai.com/api/reference/resources/videos/methods/create): `POST /videos` to create, `GET /videos/{id}` to poll and `GET /videos/{id}/content` to download. The selected provider needs to offer this compatible protocol (OpenAI has shut down its own API). Other task protocols belong in provider plugins through the optional `video` capability.

The same page configures auxiliary image understanding, automatic attachment analysis and the optional `analyze_image` tool. Native vision models receive original images directly; historical observations are saved and reused.

## Custom providers {#custom-providers}

A provider ZIP executes local code, so verify its source. To build one, export the SDK and development Skill from the import dialog, then see [Development & SDKs](../reference/development).

When a request fails, open **View request details**. Review prompts, code and file contents before sharing a report. Keys are redacted, but the report may still contain private data.
