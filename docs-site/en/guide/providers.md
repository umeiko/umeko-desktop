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
A preset name does not imply subscription sign-in. Claude Code / Codex presets use official API Keys. Kimi Code Keys differ from Moonshot platform Keys; subscription Keys may not work with pay-as-you-go endpoints. Check the selected site and your account permissions.
:::

## Multiple accounts and aliases {#multiple-accounts-and-aliases}

The first unnamed account appears as `Kimi`. An alias such as “Work” produces `Kimi(Work)`; a second unnamed account becomes `Kimi(2)`. You can add multiple accounts from one provider. Duplicate names are rejected or skipped.

Adding an account does not immediately send a paid validation request. Model access still depends on the provider's permissions. Check the model selector after saving.

## Network and model settings {#network-and-model-settings}

Use a provider card's small gear to choose the system proxy, a direct connection or a custom HTTP(S) proxy. Settings are per provider and separate from npm networking for Pi extensions.

Model settings allow context-length and vision overrides. Enable these only when the upstream model supports them; entering a larger number does not change the model's capabilities.

## Multimodal models {#multimodal-models}

In **Settings → Accounts & providers → Multimodal models**, choose an existing account and model separately for image and speech generation. Select from the model catalogue or enter a raw upstream model ID. Generation reuses the account's credentials and network settings, with no separate Key or new vendor presets. The upstream service must support the selected generation endpoint and parameters.

Images default to a count of `1`, with optional default size, quality and format. Speech requires a manually entered voice ID supported by the provider, with format `mp3` and speed `1` by default. Every call requests permission before sending the prompt or text, including in auto mode. There is currently no always-allow option.

Files are saved in the current chat workspace, adding a suffix if a name already exists. Images appear as thumbnails and audio as clickable file cards; neither opens or plays automatically. The Agent receives file paths and text. Generation does not put image pixels into model context.

Video generation is unavailable; asynchronous jobs, progress and cancellation are planned for a separate PR. Image understanding is reserved for #49, whose design remains undecided; this feature adds no controls or implementation for it.

## Custom providers {#custom-providers}

A provider ZIP executes local code, so verify its source. To build one, export the SDK and development Skill from the import dialog, then see [Development & SDKs](../reference/development).

When a request fails, open **View request details**. Review prompts, code and file contents before sharing a report. Keys are redacted, but the report may still contain private data.
