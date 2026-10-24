# API proxy provider menus and connection addresses

Settings → API proxy → Model mappings first lists provider accounts. Open one provider to edit its model aliases; Back returns to the provider list. Model editors are created only for the selected provider. Unsaved mappings survive switching providers and API Key administration. Saving validates all provider aliases together, so global alias uniqueness and models belonging to other accounts are preserved. Plugin model IDs stay read-only; context/vision overrides retain their existing controls.

Connection addresses have no editable host selector. The read-only OpenAI and Anthropic Base URLs have copy buttons. Local mode uses `127.0.0.1`. After saving LAN mode, the URLs automatically use an available local IPv4 address, preferring physical Wi-Fi/Ethernet interfaces over common Docker/VPN adapters. Address enumeration sends no discovery traffic. A refresh button and visible-page timer handle network changes.

LAN mode still binds the public service to `0.0.0.0`; this is never shown as a client connection address. If there is no usable LAN address, show the missing-address hint and disable copying rather than presenting loopback as a LAN endpoint. Turning LAN mode off restores loopback URLs. The private agent channel remains loopback-only. Existing key authentication, listener rollback and protocol paths are unchanged.
