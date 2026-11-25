# API proxy provider menus and connection addresses

Settings → API proxy → Model mappings first lists provider accounts. Open one provider to edit its model aliases; Back returns to the provider list. Unsaved mappings are kept when you switch providers or manage API Keys. Saving validates the aliases of all providers together, so every alias stays globally unique. Plugin model IDs are read-only; context and vision overrides use their usual controls.

Connection addresses show read-only OpenAI and Anthropic Base URLs with copy buttons. Local mode uses `127.0.0.1`. After you save LAN mode, the URLs use an available local IPv4 address, preferring physical Wi-Fi/Ethernet interfaces over common Docker/VPN adapters. Addresses are read locally, without network discovery. Use the refresh button after a network change; the page also refreshes periodically while visible.

In LAN mode the service listens on `0.0.0.0` and the page shows a concrete LAN address for clients. When no LAN address is available, the page shows a hint and copying is disabled. Turning LAN mode off switches back to loopback URLs. The private agent channel always stays on loopback.
