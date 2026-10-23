# Deliver images and files in chat

Umeko provides Pi with the built-in `submit_to_chatbox` tool. It works with text-only models as well as vision models: displaying an image to the user does not send its pixels to the model.

```json
{
  "items": [
    {"path": "outputs/chart.png", "kind": "image", "title": "Results", "caption": "Generated chart"},
    {"path": "outputs/report.pdf", "kind": "file", "title": "Report"}
  ]
}
```

The tool accepts up to 12 local files or directories per call, including absolute paths, `file:` URLs and paths relative to the current chat workspace. `kind` is optional and defaults to automatic image detection. Download remote images to a local file before submitting them. Missing files produce a tool error; when a batch has valid and invalid entries, the valid entries are delivered and the response lists failures.

PNG, JPEG, WebP, GIF and BMP files support inline static previews. Preview loading is asynchronous, limited to 20 MiB and 16 million pixels, and downsampled to at most 1600 × 1000. Larger images retain their compact file card. The client caches metadata so streaming replies do not repeatedly inspect or decode the same image.

Files appear as compact, single-line chips. Click to open; the right-click menu provides **Attach to chat**, **Copy file**, **Copy path**, and **Show in folder**. Copy file places the file on the system clipboard so it can be pasted into a file manager. Windows and macOS reveal/select the file; Linux opens its containing directory. Full paths appear on hover. Image captions support conversation text selection. Click an inline image to open the full-window preview, use the wheel to zoom, drag to pan and click without dragging to close. Files are opened only after a user click.

Drag files anywhere in the chat area to attach them. The app comes to the foreground and focuses the input after a drop, so typing can begin immediately.

Delivery references are stored in Pi's native session, including submissions made through nested tools such as codemode. Reopening, restarting and branching preserve the cards. The original files stay in their existing locations; the session does not bundle file contents or insert base64 data into the model context. If a file is moved or removed, the open action reports that it is unavailable.
