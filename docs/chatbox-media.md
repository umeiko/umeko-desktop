# Deliver images, files and webpages in chat

Umeko provides Pi with the built-in `submit_to_chatbox` tool. It works with text-only models as well as vision models: displaying an image to the user does not send its pixels to the model.

```json
{
  "items": [
    {"path": "outputs/chart.png", "kind": "image", "title": "Results", "caption": "Generated chart"},
    {"path": "outputs/report.pdf", "kind": "file", "title": "Report"}
  ]
}
```

The tool accepts 1–12 entries per call: local files/directories or HTTP(S) URLs. Local sources accept absolute paths, `file:` URLs and paths relative to the current chat workspace. `kind` is optional and defaults to automatic image detection. Download remote images to a local file before submitting them. Missing files produce a tool error; when a batch has valid and invalid entries, the valid entries are delivered and the response lists failures.

PNG, JPEG, WebP, GIF and BMP files support inline static previews. Preview loading is asynchronous, limited to 20 MiB and 16 million pixels, and downsampled to at most 1600 × 1000. Larger images retain their compact file card. The client caches metadata so streaming replies do not repeatedly inspect or decode the same image.

Files appear as compact, single-line chips. Click to open; the right-click menu provides **Attach to chat**, **Copy file**, **Copy path**, and **Show in folder**. Copy file places the file on the system clipboard so it can be pasted into a file manager. Windows and macOS reveal/select the file; Linux opens its containing directory. Full paths appear on hover. Image captions support conversation text selection. Click an inline image to open the full-window preview, use the wheel to zoom, drag to pan and click without dragging to close. Files are opened only after a user click.

Drag files anywhere in the chat area to attach them. The app comes to the foreground and focuses the input after a drop, so typing can begin immediately.

Delivery references are stored in Pi's native session, including submissions made through nested tools such as codemode. Reopening, restarting and branching preserve the cards. The original files stay in their existing locations; the session does not bundle file contents or insert base64 data into the model context. If a file is moved or removed, the open action reports that it is unavailable.

## Webpage delivery

Submit an HTTP(S) URL in `path`, optionally with `kind: "web"`. URLs with embedded credentials and other schemes are rejected. A successful fresh Agent submission opens the single-page Qt WebView side pane; the same URL reloads it and a different URL replaces the current page. Background-session events and history replay never open it automatically.

Single-click a delivered URL card to open or reopen the side pane. Its right-click menu contains exactly **Open**, **Copy URL**, and **Attach to chat**. Open uses the system default browser. Attach to chat creates a URL attachment chip, preserves the current draft, and focuses the composer; it does not open the pane. URL attachments retain their full addresses when sent and restored from history. The side pane has back, forward, reload, an address field and close; no tabs or standalone open button.

A URL submission adds a `webview` object to the text tool response. Its status is `ready`, `component_required`, `restart_required`, or `unavailable`. A file-only submission has no `webview` field. Only `component_required` carries the download/install instructions and pinned package metadata; those instructions are not inserted into the system prompt, permanent tool description, or app UI. See the exact registered description, prompt snippet, guidelines and parameters in [`runtime/chatbox.mjs`](../runtime/chatbox.mjs), and the conditional return in [`runtime/webview-component.mjs`](../runtime/webview-component.mjs).

## Parameters and results

`items` is required and contains 1–12 objects. Each item requires `path` (1–8192 characters). Optional fields are `kind` (`auto`, `image`, `file`, `web`, `markdown`, `code`, `text`), `title` (up to 160 characters), and `caption` (up to 1000 characters). Directories are detected automatically. HTTP(S) paths are treated as webpages regardless of `kind`; submitting a remote image URL previews its webpage, so download it first when inline image delivery is intended.

The text result is JSON with `submitted` (`path`, resolved `kind`, `title`), `errors` (`path`, `message`), and `webview` for URL submissions. A batch with no valid entries throws a tool error. Desktop presentation details remain in `details.umekoChatbox` with `version: 1` and `items`, and a native `umeko-chatbox` custom session entry preserves the references for nested calls and history.

## Local document and code preview

Markdown (`.md`, `.markdown`, `.mdown`), common source-code/configuration files, and text files (`.txt`, `.log`, `.csv`, `.tsv`, `.rst`) open in the same side pane. Explicit `kind: "markdown"`, `"code"`, or `"text"` can select a preview for an unrecognized filename. Directories and other binary document formats retain their ordinary cards. Markdown provides source/rendered switches. Local static HTML provides source/webpage switches when Qt WebView is available. Choices are saved globally and independently for Markdown and HTML, including across restarts. Source and Markdown preview do not require Qt WebView or the optional Linux WebEngine component. Static HTML is served through a loopback-only, per-document capability URL, with relative static assets confined to its directory; hidden files, directory listings, traversal and assets outside that directory are rejected. HTML above 4 MiB falls back to bounded source; individual static assets are limited to 32 MiB. The browser is released when switching back to source or closing the preview.

Markdown renders headings, emphasis, tables, lists and fenced code using Qt's document renderer. Embedded local/remote resources are blocked, and links open in the system browser only after a user click. Code uses the app's existing syntax highlighter for supported languages; text remains selectable and copyable. The preview toolbar copies the displayed text or opens the original file with its system association. A fresh foreground `submit_to_chatbox` event opens the preview; clicking a delivered document card reopens it. Background sessions and history replay do not open it automatically.

The document reader runs off the GUI thread and reads at most 256 KiB. It retains at most approximately 48,000 characters, 1,000 source lines and 2,000 characters per line. A visible notice identifies partial previews, and the original file stays unchanged. Ordinary Markdown is rendered richly only within 24,000 characters/400 lines, with limits on long lines, table/link complexity and resulting HTML size; complex input falls back to plain text. Syntax highlighting is disabled above 24,000 characters/500 lines or 1,000 characters per line. Binary data and missing/unreadable files show an error without entering the document layout. UTF-8 and BOM-marked UTF-16 are supported.

At most one read and one latest pending request are retained. Switching files discards stale results; closing the pane or switching sessions cancels pending delivery and releases the displayed document. Preview contents are not copied into Pi tool results or its session history: only file references are stored.

Both the web address bar and document pane share a draggable left divider. Resizing follows the pointer directly, retains the chosen width across page/document switches and close/reopen within the current window, and clamps it to leave usable chat space. Open/close still use PID motion. First focus/click on the URL field selects the complete URL; subsequent clicks position the cursor normally.

## 当前工具提示词原文（审阅）

以下为当前实际注册的工具定义，两个版本一致。新增的产物展示建议位于 `promptGuidelines`。

```json
{
  "name": "submit_to_chatbox",
  "label": "展示产物与网页",
  "exposure": "direct",
  "description": "Show artifacts directly in Umeko chat. Accept local files/folders as absolute paths, file URLs or workspace-relative paths, and HTTP(S) URLs. Images preview inline independently of model vision support. Markdown, source code and plain text open in the side pane. Markdown offers source/rendered views; local static HTML offers source/webpage views when the WebView component is available. The desktop remembers the user's view choice globally per file type. Large/complex files use bounded partial, simplified or source previews. Other files have cards for opening or revealing their folder. HTTP(S) URLs open the single-page side WebView; the same URL reloads it and a different URL replaces it. Users can click delivered cards to reopen previews. URL context actions open the system browser, copy the URL or attach it to chat. Download remote images before submitting them as inline images.",
  "promptSnippet": "Use submit_to_chatbox to show generated artifacts, images, documents, code or webpages in Umeko.",
  "promptGuidelines": [
    "For a better user experience, after creating or updating a user-facing artifact, prefer submitting its local path with submit_to_chatbox rather than only mentioning its path. Also use it when the user asks to see an image or receive a generated/downloaded file. Markdown, code and text are previewed in the side pane; images render independently of model vision support. Large-file previews may be truncated or simplified; the original file remains available."
  ],
  "parameters": {
    "type": "object",
    "required": [
      "items"
    ],
    "properties": {
      "items": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "path"
          ],
          "properties": {
            "path": {
              "type": "string",
              "minLength": 1,
              "maxLength": 8192
            },
            "kind": {
              "anyOf": [
                {
                  "type": "string",
                  "const": "auto"
                },
                {
                  "type": "string",
                  "const": "image"
                },
                {
                  "type": "string",
                  "const": "file"
                },
                {
                  "type": "string",
                  "const": "web"
                },
                {
                  "type": "string",
                  "const": "markdown"
                },
                {
                  "type": "string",
                  "const": "code"
                },
                {
                  "type": "string",
                  "const": "text"
                }
              ]
            },
            "title": {
              "type": "string",
              "maxLength": 160
            },
            "caption": {
              "type": "string",
              "maxLength": 1000
            }
          }
        },
        "minItems": 1,
        "maxItems": 12
      }
    }
  }
}
```

## 缺少 Linux 组件时的返回原文

仅提交网页且缺少 Linux 组件时，下列对象作为返回 JSON 的 `webview` 字段出现；不会注入系统提示词、固定工具说明或应用界面。示例 `/path/to/umeko/components` 会替换为用户的组件目录。组件链接指向固定版本的独立资源 Release。本地文档预览不会触发这段安装提示。

```json
{
  "status": "component_required",
  "releaseUrl": "https://github.com/umeiko/umeko-desktop-cpp/releases/tag/qt-webengine-6.10.2-linux-x64-v1",
  "downloadUrl": "https://github.com/umeiko/umeko-desktop-cpp/releases/download/qt-webengine-6.10.2-linux-x64-v1/Umeko-qt-webengine-6.10.2-linux-x64-v1.zip",
  "filename": "Umeko-qt-webengine-6.10.2-linux-x64-v1.zip",
  "bytes": 114536308,
  "sha256": "e892f306a5956a784100cabcd5ea25cf3c2b782f177842b22d115b4fa3029ffe",
  "installDirectory": "/path/to/umeko/components/qt-webengine-6.10.2-linux-x64-v1-e892f306a5956a78",
  "activationFile": "/path/to/umeko/components/active.json",
  "activation": {
    "id": "qt-webengine-6.10.2-linux-x64-v1",
    "sha256": "e892f306a5956a784100cabcd5ea25cf3c2b782f177842b22d115b4fa3029ffe",
    "directory": "qt-webengine-6.10.2-linux-x64-v1-e892f306a5956a78"
  },
  "instructions": "This URL was delivered as a chat link, but the Linux side WebView needs an optional Qt WebEngine component. Tell the user why the pane did not open and provide the official release page and ZIP URL above. If GitHub access is blocked, the user can download using an accessible network or another device and give you the local ZIP path. You may use your existing tools to obtain the package. To install: verify the ZIP size and SHA-256 exactly against the values above before extracting; extract its contents into installDirectory, keeping lib/, libexec/, plugins/, qml/, resources/ and manifest.json directly inside that directory. Ensure libexec/QtWebEngineProcess has executable permission (chmod 755). Then atomically write the activation JSON above to activationFile. Do not modify system Qt or require sudo. Tell the user to restart Umeko when convenient, then resubmit the URL. Do not stop agents or restart the app automatically."
}
```
