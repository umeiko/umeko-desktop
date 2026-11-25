# Common provider accounts

In **Settings → Accounts and providers**, the **常见供应商** card sits alongside **自定义供应商** and **API 供应商**. Click its **+** button, select a brand, and enter the official API Key. Each Key form includes an **申请 API Key** hyperlink to that provider’s official Key page. Common accounts stay in their own card; manually configured API accounts stay in the API card. The account alias is optional. Endpoint, protocol, model IDs, context sizes and vision capabilities come from `app/provider-presets.json`; adding an account sends no request to the provider. The new account is selected when the current conversation is idle; a running conversation keeps its model.

## Names and multiple accounts

The first unnamed account is `Kimi`. An explicit alias such as `Work` gives `Kimi(Work)`. An unnamed second account is `Kimi(2)`, even when the first account has an explicit alias. Later accounts skip occupied names. Explicit duplicate account names are rejected. Model aliases are unique across all accounts; upstream model IDs stay as they are. Editing an account keeps its preset identity, credentials and wire protocol. API Keys are kept in the protected credential storage.

## Presets and sources

Claude Code and Codex entries use the official Claude/OpenAI APIs and sign in with an API Key. Kimi Code uses a Kimi Code Key, which is separate from Moonshot platform API Keys. Your account's permissions decide which of the configured models you can call.

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

The list has six provider entries. **GLM Coding Plan** and **MiniMax 订阅** have a site dropdown in their Key forms with two website-and-region options; China is selected by default. GLM displays `zcode.z.ai/cn（中国大陆）` and `z.ai（国际）`; MiniMax displays `platform.minimax.cn（中国大陆）` and `platform.minimax.io（国际）`. Selecting International uses Z.ai for GLM and MiniMax’s international site for MiniMax, changing the endpoint, model preset and Key link together. Changing sites clears the entered Key and keeps the optional alias. Closing the popup, returning to the provider list or choosing another provider resets the site selection to China.

GLM’s international link opens [Z.ai API Keys](https://z.ai/manage-apikey/apikey-list); use the Personal Coding Plan tab. MiniMax’s links open the matching domestic or international M Plan console. Use a subscription Key: both GLM configurations use the subscription endpoints, and standard pay-as-you-go Keys belong to the standard API. Each account stores its provider family and chosen region, keeps its own credentials and receives globally unique model aliases. International GLM accounts use the Z.ai name and icon (`Z.ai`, `Z.ai(Work)`, `Z.ai(2)`). MiniMax accounts follow the usual name/alias rules across regions. Editing an account keeps its saved region. Older domestic accounts without a saved region are treated as China accounts.

Which tools a subscription may be used with is decided by the provider and your account. Umeko identifies itself as Umeko in its requests.

GLM-5.3 is text-only; GLM-5.3-Flash accepts images. Both use a 1,000,000-token window. The subscription does not include FlashX, so it is not listed. MiniMax M Plan supplies MiniMax-M3.1-Flash with image input and a 524,288-token client window. Sources: [GLM-5.3](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3), [GLM-5.3-Flash](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash), [MiniMax client configuration](https://platform.minimax.cn/docs/m-plan/other-tools).

OpenAI recommends its general-purpose coding models for Codex, so the Codex preset uses `gpt-6.1-sol`. The Responses bridge supports streaming text, function-call declarations and argument deltas, images, tool-result history, usage and output limits, and reports interrupted streams as errors.

The GLM entry and both regional account variants use the official black-and-white ZCode favicon, matching the Z brand mark. Website labels (`siteUrl`) are for display; requests use the model API (`baseUrl`) and Key links use the Key console (`keyUrl`). [ZCode’s own connection guide](https://zcode.z.ai/cn/docs/configuration) also uses `open.bigmodel.cn/api/coding/paas/v4` and a BigModel Key for the domestic subscription.

The provider icons are stored locally. Source URLs, hashes and the Claude and MiniMax icon library license are recorded in `app/icons/providers/sources.json`; LobeHub's MIT license is included under `licenses/LobeHub-Icons.txt`.

## Verification

Python: `python -m unittest tests.test_common_providers tests.test_openai_responses`, then `python tests/common_providers_ui_smoke.py`. Native: `ctest --test-dir build --output-on-failure` and `node --test tests/gateway.test.mjs tests/openai-responses.test.mjs`. Tests use synthetic keys and local HTTP fixtures.
