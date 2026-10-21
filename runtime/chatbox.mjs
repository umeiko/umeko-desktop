// Desktop delivery tool. Persist references in Pi's own toolResult details;
// never insert base64 payloads into the model context or execute/open a file.
import { Type } from "typebox";
import { stat, realpath } from "node:fs/promises";
import { basename, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";

export const CHATBOX_TOOL = "submit_to_chatbox";
export function chatboxItems(name, result) {
  const payload = result?.details?.umekoChatbox;
  return name === CHATBOX_TOOL && !result?.isError && payload?.version === 1 && Array.isArray(payload.items) ? payload.items.slice(0, 12) : [];
}

export function chatboxExtension(pi) {
  pi.registerTool({
    name: CHATBOX_TOOL, label: "展示图片与文件", exposure: "direct",
    description: "Display local images and deliver file or folder cards directly in the user's Umeko chat. Accepts absolute paths, file URLs, or paths relative to the current workspace. Images preview inline; file cards let the user open a file or reveal its folder. Works with text-only models; never opens files automatically. Download remote images to a local file before submitting.",
    promptSnippet: "Show local images and deliver files to the user in chat.",
    promptGuidelines: ["When the user asks to see an image or receive a generated/downloaded file, use submit_to_chatbox with its local path. The chat UI renders images independently of model vision support."],
    parameters: Type.Object({items: Type.Array(Type.Object({
      path: Type.String({minLength: 1, maxLength: 8192}),
      kind: Type.Optional(Type.Union([Type.Literal("auto"), Type.Literal("image"), Type.Literal("file")])),
      title: Type.Optional(Type.String({maxLength: 160})),
      caption: Type.Optional(Type.String({maxLength: 1000})),
    }), {minItems: 1, maxItems: 12})}),
    async execute(_id, params, signal, _update, ctx) {
      const items = [], errors = [];
      for (const input of params.items) {
        if (signal?.aborted) throw new Error("提交已取消");
        try {
          let path = input.path.trim();
          if (/[\0\r\n]/.test(path)) throw new Error("路径包含无效字符");
          if (/^file:/i.test(path)) path = fileURLToPath(path);
          else if (/^[a-z][a-z\d+.-]*:/i.test(path) && !/^[a-z]:[\\/]/i.test(path)) throw new Error("请提供本地文件路径；远程图片请先下载到工作目录");
          if (/^~(?=[/\\]|$)/.test(path)) path = homedir() + path.slice(1);
          path = await realpath(isAbsolute(path) ? path : resolve(ctx.cwd, path));
          const info = await stat(path);
          if (!info.isFile() && !info.isDirectory()) throw new Error("只支持普通文件或目录");
          const image = /\.(png|jpe?g|webp|gif|bmp)$/i.test(path);
          if (input.kind === "image" && (!image || !info.isFile())) throw new Error("图片仅支持 PNG、JPEG、WebP、GIF、BMP");
          items.push({path, name: basename(path), kind: info.isDirectory() ? "folder" : input.kind !== "file" && image ? "image" : "file",
            title: input.title?.trim() || basename(path), caption: input.caption || "", bytes: info.size, modified: info.mtimeMs});
        } catch (error) { errors.push({path: input.path, message: error.code === "ENOENT" ? "文件不存在" : error.message}); }
      }
      if (!items.length) throw new Error(errors.map(item => `${item.path}: ${item.message}`).join("\n"));
      // Nested tool results keep only a bounded call summary in Pi. A native
      // custom entry preserves delivery details on the same branch as the call.
      pi.appendEntry("umeko-chatbox", {version: 1, toolCallId: _id, items});
      return { content: [{type: "text", text: JSON.stringify({submitted: items.map(({path, kind, title}) => ({path, kind, title})), errors})}],
        details: {umekoChatbox: {version: 1, items}} };
    },
  });
}
