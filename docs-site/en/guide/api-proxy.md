# API proxy {#api-proxy}

The optional API proxy lets other clients request models through providers configured in Umeko. It is separate from the private local channel used by the embedded agent.

## Map models {#map-models}

In **Settings → API proxy**, select a provider and open its submenu to set model aliases. Return to configure other providers, then save all mappings. Public model aliases must be unique across accounts.

[![Model mappings inside a provider submenu](/images/model-mapping-en.png)](/images/model-mapping-en.png)

*Select a provider, then edit its model aliases. Saving mappings does not start the proxy.*

## Copy connection details {#copy-connection-details}

1. Save mappings and create an API Key for the client.
2. Start the service and copy its OpenAI or Anthropic **Base URL**.
3. In the client, enter that address, the proxy API Key and the mapped model alias.

Use a Key created by the proxy, not the upstream provider's own Key.

[![API proxy settings and copyable Base URLs](/images/api-proxy-en.png)](/images/api-proxy-en.png)

*Configure the connection and copy a Base URL after starting the service. The demo service is stopped and has no public listener.*

## Local and LAN modes {#local-and-lan-modes}

Local mode displays `127.0.0.1`. After saving LAN mode, copyable addresses use an available local IPv4 address. If none is available, Umeko shows a hint. Do not use `0.0.0.0` as a client address.

Enable LAN access only when another device on the network needs it, and check your OS firewall. Avoid accidentally exposing the service to the public internet. Clients still need a Key. Switching back to local mode restores loopback addresses.

## Manage Keys {#manage-keys}

Use named Keys for separate clients and disable or revoke unused ones. To troubleshoot, check that the service is running, the port is reachable and the model alias matches, then verify the provider itself works in an Umeko conversation.
