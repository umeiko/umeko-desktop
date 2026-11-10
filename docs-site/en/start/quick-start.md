# Quick start {#quick-start}

Umeko brings Pi Coding Agent into a native desktop app: chat around projects, use your own model providers, and inspect tools and subagents as they work.

## 1. Install the app {#_1-install-the-app}

Choose your platform and edition in [Install & update](./install). Complete packages include their runtimes; you do not need to install Python, Node.js or a global `pi` first.

## 2. Connect a model {#_2-connect-a-model}

Open **Settings → Accounts and providers**. For a common provider, choose its brand and site, then enter the appropriate API Key. Other services use an API provider or a trusted provider ZIP.

Select an available model after adding the account. Subscription logins and API Keys each have their own permissions and billing; see [Accounts & models](../guide/providers).

## 3. Open a project {#_3-open-a-project}

Add a project from the sidebar or drop its folder there. Open a conversation, check the working directory and model, then describe your task.

Try a small first task:

> Read this project and explain how to run it, what its main directories do, and three improvements you would suggest. Do not edit any files yet.

[![Projects and chat in the pure-white theme](/images/chat-en.png)](/images/chat-en.png)

*Choose a project and conversation on the left, then a model and task at the bottom. Click screenshots to view them at full size.*

::: tip About the screenshots
Screenshots show the Python / Qt interface from current main with demo data and the pure-white theme. English pages use separately captured English UI.
:::

## 4. Follow along and steer {#_4-follow-along-and-steer}

- Expand thinking and tool records to inspect them. The thinking section shows reasoning the model returns and stays hidden when there is none.
- While a task runs, **Enter** queues a follow-up and **Ctrl+S** prioritizes your intervention.
- After an agent produces a report, image or code, ask it to “show it with submit” to view the artifact in chat or the side pane.

## Next steps {#next-steps}

[Manage conversations](../guide/conversations) · [Try subagents](../guide/subagents) · [Things to try](../guide/tips)
