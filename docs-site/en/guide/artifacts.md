# Files & artifact previews {#files-artifact-previews}

Ask the agent to bring its work into view:

> Save your analysis as Markdown, then show it to me with submit.

`submit_to_chatbox` accepts local files, folders and HTTP(S) addresses. Cards keep a reference to the original and open the file from its current location.

## How content appears {#how-content-appears}

| Type | View |
| --- | --- |
| Images | Inline preview; click to enlarge, wheel to zoom and drag to pan |
| Markdown | Source / rendered switch in the side pane |
| Code, TXT and logs | Text preview, with syntax colors for supported languages |
| Local static HTML | Source / webpage switch; webpage mode needs WebView |
| HTTP(S) addresses | A single-page side browser with back, forward, reload and an address bar |
| Other files and folders | Cards for opening with a system app or revealing in the file manager |

Markdown and HTML remember their last view modes separately. Large or complex documents show a partial preview, using source or plain text when needed. Open Office or PDF files in a system app to read them in full.

[![Rendered Markdown artifact preview](/images/artifact-rendered-en.png)](/images/artifact-rendered-en.png)

*Click report.md in chat to see the formatted report. Use Source / Rendered at the top to change views.*

[![Source view of the same Markdown file](/images/artifact-source-en.png)](/images/artifact-source-en.png)

*Source view shows the original contents of the same file.*

## Cards and the side pane {#cards-and-the-side-pane}

Click a delivered webpage card to open the pane. Its context menu offers **Open** in the system browser, **Copy URL** and **Attach to chat**. Local files offer copying, revealing and attachment actions. Attached files join your current draft, and you decide when to send it.

Drag the pane's left edge to resize it; close it to release the preview. A new agent URL submission replaces the page; the same URL reloads it. The pane shows one page at a time.

## Linux webpage component {#linux-webpage-component}

The base package omits the full Qt WebEngine. When it is missing, the webpage submission tool's result gives the agent the official ZIP, checksum and installation instructions. Give the agent a local ZIP path to install, or use the system browser first.

If GitHub is inaccessible, download the official asset on an accessible network or another device and bring the ZIP to this machine. After installation, restart the app at a convenient time. Markdown, code and text previews work without this component.
