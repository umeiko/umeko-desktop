# Pi package market

When a task needs a dedicated tool that is not installed, the agent checks
the current tools and `pi list`, searches npm packages tagged `pi-package`,
reads package details and audit notes, and installs a selected exact version.
Umeko reloads the same Pi session after the turn, then sends its existing hidden
command-results message so the agent can continue the original task.

The small wrench beside Send/Stop opens package management without leaving
the conversation. It is a user-requested shortcut to the same controls in
**Settings → Agent → Pi**, rather than another configuration workflow.

- **Ask every time (default):** the existing extension approval dialog asks
  before each agent install. Declining installs nothing.
- **Fully automatic:** the agent may install and continue without a confirmation.
  Only the user can change this setting, in the panel or settings page.
- The panel shows third-party package versions, who installed them and why,
  last-used time, call count and audit notes. Enable/disable uses Pi's existing
  resource settings. Uninstall uses native `pi remove`, including packages
  registered with relative local paths. Local source files are preserved.

Both `marketplace_install` and `run_pi_command install` use one permission
check and the existing native installer. `config_umeko` cannot change the mode
or use the manual settings installer to bypass it. A declined request must not
be retried without a new user decision.

Search, details and audit use Umeko's **network.npm** registry, optional `.npmrc`
and CA overrides. When a mirror lacks the search endpoint, an exact package-name
lookup is available; results explicitly say `method: exact-name` and require
the `pi-package` keyword. This is a single-package lookup, not a full market search.
Audit notes describe metadata and source keyword matches; they are not a safety
guarantee. The package is pinned to the inspected version when installed by
`marketplace_install`.

`package-records.json` lives next to the profile settings and survives restarts.
It stores installation metadata and per-package call counts/times, without tool
arguments. Tool ownership comes from Pi `getAllTools().sourceInfo` and the
resource loader's package metadata. Existing packages with no install history
are shown as having an unknown installer.

## Reused implementation

| Part | Source and adaptation |
| --- | --- |
| Search, detail, audit | MIT `pi-marketplace` 0.1.3 API/tool definitions and keyword scanner; configured registry/CA, pinned tarball scan and explicit fallback are desktop adaptations. |
| Install and continuation | Existing `runtime/pi-commands.mjs` native CLI, queued `/reload` and hidden `umeko-pi-command-results`; no second agent installer. |
| Confirmation | Existing `ctx.ui.confirm` → `ui_request` → `ApprovalDialog` → `respondApproval`. |
| List and actions | MIT `pi-extmgr` 0.4.2 source/scope grouping and enable/disable/remove action model, adapted to Umeko's existing `PiManagement` and `extensions.enable` methods. |
| Last used and unused order | Claude Code Installed-tab presentation; no source copied. |
| Wrench/popup/settings | Existing `Composer` ActionButton row, `PidPopup`, `ExtensionManager`, and theme components. |
| Wrench glyph | Lucide `icons/wrench.svg` (ISC), using the existing icon stroke weight. |
| New integration | Permission enforcement, profile records, sourceInfo usage events and QML bindings connect existing implementations; none of those sources provides Umeko's Python/JSONL bridge. |

See [third-party notices](../THIRD_PARTY_NOTICES.md) for retained licenses and
[npm networking](npm-and-network.md) for registry configuration.
