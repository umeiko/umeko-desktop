// Desktop delivery tool. Persist references in Pi's own toolResult details;
// never insert base64 payloads into the model context or execute/open a file.
import { Type } from "typebox";
import { stat, realpath } from "node:fs/promises";
import { basename, extname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";

import { webviewStatus } from "./webview-component.mjs";

export const CHATBOX_TOOL = "submit_to_chatbox";
function documentKind(path, requested) {
  if (['markdown','code','text'].includes(requested)) return requested;
  if (requested === 'image') return '';
  const suffix = extname(path).slice(1).toLowerCase(), name = basename(path).toLowerCase();
  if (['md','markdown','mdown'].includes(suffix)) return 'markdown';
  if (['dockerfile','makefile','cmakelists.txt','.gitignore','.env'].includes(name)) return 'code';
  if (['txt','log','csv','tsv','rst','text'].includes(suffix)) return 'text';
  if ('c h cpp hpp cxx cc cs java kt go rs py pyw js mjs cjs jsx ts tsx json jsonc yaml yml toml ini cfg conf css scss html htm xml svg sh bash zsh fish ps1 bat cmd sql diff patch vue svelte qml cmake rb php lua dart swift r asm'.split(' ').includes(suffix)) return 'code';
  return '';
}
export function chatboxItems(name, result) {
  const payload = result?.details?.umekoChatbox;
  return name === CHATBOX_TOOL && !result?.isError && payload?.version === 1 && Array.isArray(payload.items) ? payload.items.slice(0, 12) : [];
}

export function chatboxExtension(pi, getWebview = () => ({})) {
  pi.registerTool({
    name: CHATBOX_TOOL, label: "展示产物与网页", exposure: "direct",
    description: "Show artifacts directly in Umeko chat. Accept local files/folders as absolute paths, file URLs or workspace-relative paths, and HTTP(S) URLs. Images preview inline independently of model vision support. Markdown, source code and plain text open in the side pane. Markdown offers source/rendered views; local static HTML offers source/webpage views when the WebView component is available. The desktop remembers the user's view choice globally per file type. Large/complex files use bounded partial, simplified or source previews. Other files have cards for opening or revealing their folder. HTTP(S) URLs open the single-page side WebView; the same URL reloads it and a different URL replaces it. Users can click delivered cards to reopen previews. URL context actions open the system browser, copy the URL or attach it to chat. Download remote images before submitting them as inline images.",
    promptSnippet: "Use submit_to_chatbox to show generated artifacts, images, documents, code or webpages in Umeko.",
    promptGuidelines: ["For a better user experience, after creating or updating a user-facing artifact, prefer submitting its local path with submit_to_chatbox rather than only mentioning its path. Also use it when the user asks to see an image or receive a generated/downloaded file. Markdown, code and text are previewed in the side pane; images render independently of model vision support. Large-file previews may be truncated or simplified; the original file remains available."],
    parameters: Type.Object({items: Type.Array(Type.Object({
      path: Type.String({minLength: 1, maxLength: 8192}),
      kind: Type.Optional(Type.Union([Type.Literal("auto"), Type.Literal("image"), Type.Literal("file"), Type.Literal("web"), Type.Literal("markdown"), Type.Literal("code"), Type.Literal("text")])),
      title: Type.Optional(Type.String({maxLength: 160})),
      caption: Type.Optional(Type.String({maxLength: 1000})),
    }), {minItems: 1, maxItems: 12})}),
    async execute(_id, params, signal, _update, ctx) {
      const items = [], errors = [];
      let webview;
      for (const input of params.items) {
        if (signal?.aborted) throw new Error("提交已取消");
        try {
          let path = input.path.trim();
          if (/[\0\r\n]/.test(path)) throw new Error("路径包含无效字符");
          if (/^https?:/i.test(path)) {
            const url = new URL(path);
            if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error("请使用不含账号密码的 HTTP(S) 网址");
            webview = await webviewStatus(getWebview());
            items.push({path:url.href, url:url.href, name:url.hostname, kind:'web', title:input.title?.trim() || url.hostname, caption:input.caption || '', presentation:webview.status === 'ready' ? 'webview' : 'external'});
            continue;
          }
          if (input.kind === 'web') throw new Error("网页仅支持 HTTP(S) 网址");
          if (/^file:/i.test(path)) path = fileURLToPath(path);
          else if (/^[a-z][a-z\d+.-]*:/i.test(path) && !/^[a-z]:[\\/]/i.test(path)) throw new Error("请提供本地文件路径；远程图片请先下载到工作目录");
          if (/^~(?=[/\\]|$)/.test(path)) path = homedir() + path.slice(1);
          path = await realpath(isAbsolute(path) ? path : resolve(ctx.cwd, path));
          const info = await stat(path);
          if (!info.isFile() && !info.isDirectory()) throw new Error("只支持普通文件或目录");
          const image = /\.(png|jpe?g|webp|gif|bmp)$/i.test(path);
          if (input.kind === "image" && (!image || !info.isFile())) throw new Error("图片仅支持 PNG、JPEG、WebP、GIF、BMP");
          items.push({path, name: basename(path), kind: info.isDirectory() ? "folder" : documentKind(path, input.kind) || (input.kind !== "file" && image ? "image" : "file"),
            title: input.title?.trim() || basename(path), caption: input.caption || "", bytes: info.size, modified: info.mtimeMs});
          if (info.isFile() && /\.html?$/i.test(path)) webview ||= await webviewStatus(getWebview());
        } catch (error) { errors.push({path: input.path, message: error.code === "ENOENT" ? "文件不存在" : error.message}); }
      }
      if (!items.length) throw new Error(errors.map(item => `${item.path}: ${item.message}`).join("\n"));
      // Nested tool results keep only a bounded call summary in Pi. A native
      // custom entry preserves delivery details on the same branch as the call.
      pi.appendEntry("umeko-chatbox", {version: 1, toolCallId: _id, items});
      return { content: [{type: "text", text: JSON.stringify({submitted: items.map(({path, kind, title}) => ({path, kind, title})), errors, ...(webview ? {webview} : {})})}],
        details: {umekoChatbox: {version: 1, items}} };
    },
  });
}
