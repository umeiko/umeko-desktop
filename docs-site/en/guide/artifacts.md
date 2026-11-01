# Files & artifact previews {#files-artifact-previews}

Ask the agent to bring its work into view:

> Save your analysis as Markdown, then show it to me with submit.

`submit_to_chatbox` accepts local files, folders and HTTP(S) addresses. Cards retain references to the originals; moving or deleting a file affects later opening.

## How content appears {#how-content-appears}

| Type | View |
| --- | --- |
| Images | Inline preview; click to enlarge, wheel to zoom and drag to pan |
| Markdown | Source / rendered switch in the side pane |
| Code, TXT and logs | Text preview, with syntax colors for supported languages |
| Local static HTML | Source / webpage switch; webpage mode needs WebView |
| HTTP(S) addresses | A single-page side browser with back, forward, reload and an address bar |
| Other files and folders | Cards for opening with a system app or revealing in the file manager |

Markdown and HTML remember their last view modes separately. Large or complex documents use bounded partial previews and may fall back to source or plain text. Originals remain unchanged. The preview is not a complete Office or PDF reader.

[![Rendered Markdown artifact preview](/images/artifact-rendered-en.png)](/images/artifact-rendered-en.png)

*Click report.md in chat to see the formatted report. Use Source / Rendered at the top to change views.*

[![Source view of the same Markdown file](/images/artifact-source-en.png)](/images/artifact-source-en.png)

*Source shows the same file without modifying its contents.*

## Cards and the side pane {#cards-and-the-side-pane}

Click a delivered webpage card to open the pane. Its context menu offers **Open** in the system browser, **Copy URL** and **Attach to chat**. Local files offer copying, revealing and attachment actions. Attaching neither sends a message nor clears the draft.

Drag the pane's left edge to resize it; close it to release the preview. A new agent URL submission replaces the page; the same URL reloads it. There are no tabs or separate controls for opening an empty browser.

## Linux webpage component {#linux-webpage-component}

The base package omits the full Qt WebEngine. When it is missing, the webpage submission tool's result gives the agent the official ZIP, checksum and installation instructions. Give the agent a local ZIP path to install, or use the system browser first.

If GitHub is inaccessible, download the official asset on an accessible network or another device and bring the ZIP to this machine. Restart manually when convenient after installation; the agent should not interrupt ongoing work. Markdown, code and text previews do not need this component.
