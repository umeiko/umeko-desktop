# Common provider accounts

In **Settings → Accounts and providers**, the **常见供应商** card sits alongside **自定义供应商** and **API 供应商**. Click its **+** button, select a brand, and enter the official API Key. Each Key form includes an **申请 API Key** hyperlink to that provider’s official Key page. Common accounts stay in their own card; manually configured API accounts stay in the API card. The account alias is optional. Endpoint, protocol, model IDs, context sizes and vision capabilities are supplied by `app/provider-presets.json`; adding an account does not send a validation request or start a paid model request. The new account is selected when the current conversation is idle; a running conversation keeps its model.

## Names and multiple accounts

The first unnamed account is `Kimi`. An explicit alias such as `Work` gives `Kimi(Work)`. An unnamed second account is `Kimi(2)`, even when the first account has an explicit alias. Later accounts skip occupied names. Explicit duplicate account names are rejected. Model aliases also avoid collisions across all accounts; the actual upstream model IDs remain unchanged. Editing an account retains its preset identity, credentials and wire protocol. API Keys stay in the existing protected credential storage and are not exposed through the QML configuration.

## Presets and sources

Reviewed 2026-10-24. Claude Code and Codex entries use the official Claude/OpenAI APIs with API Keys; they do not import subscription logins or CLI OAuth tokens. Kimi Code uses a Kimi Code Key, separate from Moonshot platform API Keys. Account permissions still determine which of the configured models can be called.

| Entry | Default model | Endpoint / protocol | Official reference |
| --- | --- | --- | --- |
| Claude Code | `claude-sonnet-5-5` | `https://api.anthropic.com/v1`, Anthropic Messages | [Claude models](https://platform.claude.com/docs/en/models/overview), [API overview](https://platform.claude.com/docs/en/api/overview) |
| Codex | `gpt-6.1-sol` | `https://api.openai.com/v1`, Responses | [Code generation](https://developers.openai.com/api/docs/guides/code-generation), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) |
| Kimi Code | `kimi-for-coding` | `https://api.kimi.com/coding/v1`, Chat Completions | [Kimi Code overview](https://www.kimi.com/code/docs/) |
| DeepSeek | `deepseek-flash` | `https://api.deepseek.com/v1`, Chat Completions | [DeepSeek API](https://api-docs.deepseek.com/) |
| GLM Coding Plan | `glm-5.3` (+ `glm-5.3-flash`) | `https://open.bigmodel.cn/api/coding/paas/v4`, Chat Completions | [Subscription models](https://docs.bigmodel.cn/cn/coding-plan/overview), [Subscription keys and endpoints](https://docs.bigmodel.cn/cn/coding-plan/notice/api-key-management) |
| GLM Coding Plan, international dropdown option (Z.ai) | `glm-5.3` (+ `glm-5.3-flash`) | `https://api.z.ai/api/coding/paas/v4`, Chat Completions | [International subscription guide](https://docs.z.ai/devpack/quick-start), [Subscription models](https://docs.z.ai/devpack/overview) |
| MiniMax 订阅 (M Plan) | `MiniMax-M3.1-Flash` | `https://api.minimax.cn/v1`, Chat Completions | [M Plan integration](https://platform.minimax.cn/docs/m-plan/other-tools), [Subscription Key](https://platform.minimax.cn/docs/m-plan/quickstart) |
| MiniMax, international dropdown option | `MiniMax-M3.1-Flash` | `https://api.minimax.io/v1`, Chat Completions | [International integration](https://platform.minimax.io/docs/m-plan/other-tools), [International subscription Key](https://platform.minimax.io/docs/m-plan/quickstart) |

The list keeps six provider entries. **GLM Coding Plan** and **MiniMax 订阅** have a site dropdown in their Key forms, with exactly two website-and-region options and China selected by default. GLM displays `zcode.z.ai/cn（中国大陆）` and `z.ai（国际）`; MiniMax displays `platform.minimax.cn（中国大陆）` and `platform.minimax.io（国际）`. Selecting International uses Z.ai for GLM and MiniMax’s international site for MiniMax, changing the endpoint, model preset and Key link together. Changing sites clears the entered Key and preserves the optional alias. Closing the popup, returning to the provider list or choosing another provider resets the site selection to China. Providers without a separate international configuration do not show the dropdown.

GLM’s international link opens [Z.ai API Keys](https://z.ai/manage-apikey/apikey-list); use the Personal Coding Plan tab. MiniMax’s links open the appropriate domestic or international M Plan console. Standard pay-as-you-go Keys are not interchangeable with subscription Keys. Neither GLM configuration falls back to the standard billing endpoint. Each account stores its provider family and chosen region separately, keeps its own credentials and receives globally unique model aliases. International GLM accounts use the Z.ai name and icon (`Z.ai`, `Z.ai(Work)`, `Z.ai(2)`). MiniMax accounts share the existing name/alias rules across regions; occupied names are skipped. Editing an account retains its saved region. Existing domestic accounts without region metadata continue to count as China accounts.

Subscription eligibility still depends on the provider’s supported tools and account permissions. Umeko sends its own client identity and does not impersonate an officially supported client. Tests do not establish a real subscription’s eligibility.

GLM-5.3 is text-only; GLM-5.3-Flash accepts images, both with a conservative 1,000,000-token window. FlashX is excluded because it is not currently in the subscription. MiniMax M Plan currently supplies MiniMax-M3.1-Flash with image input and a 524,288-token client window. Sources: [GLM-5.3](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3), [GLM-5.3-Flash](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash), [MiniMax client configuration](https://platform.minimax.cn/docs/m-plan/other-tools).

OpenAI's current guidance recommends general-purpose coding models for Codex; the deprecated GPT-5.3-Codex is not a preset default. The Responses bridge supports streaming text, function-call declarations and argument deltas, images, tool-result history, usage, output limits and explicit failure on interrupted streams. It uses the real Umeko client identity; Kimi requests do not impersonate another coding client.

The GLM entry and both regional account variants use the official black-and-white ZCode favicon, matching the Z brand mark. Website labels (`siteUrl`) are presentation metadata: they do not replace the model API (`baseUrl`) or Key console (`keyUrl`). [ZCode’s own connection guide](https://zcode.z.ai/cn/docs/configuration) still prescribes `open.bigmodel.cn/api/coding/paas/v4` and a BigModel Key for the domestic subscription.

The provider icons are stored locally. Source URLs, hashes and the Claude and MiniMax icon library license are recorded in `app/icons/providers/sources.json`; LobeHub's MIT license is included under `licenses/LobeHub-Icons.txt`.

## Verification

Python: `python -m unittest tests.test_common_providers tests.test_openai_responses`, then `python tests/common_providers_ui_smoke.py`. Native: `ctest --test-dir build --output-on-failure` and `node --test tests/gateway.test.mjs tests/openai-responses.test.mjs`. Tests use synthetic keys and local HTTP fixtures; they do not verify a real user's provider billing or model entitlements.
