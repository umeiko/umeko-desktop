// Generation uses Umeko's private gateway; provider credentials stay in Python.
// Results contain local references only, independently of the chat model's vision.
import { Type } from "typebox";
import { open, realpath, unlink } from "node:fs/promises";
import { basename, extname, join } from "node:path";
import { deliverChatboxItems } from "./chatbox.mjs";

const optionalString = maxLength => Type.Optional(Type.String({minLength: 1, maxLength}));
const formats = values => Type.Optional(Type.Union(values.map(value => Type.Literal(value))));
const filename = optionalString(180);
const mimeExtensions = new Map([
  ["image/png", ["png"]], ["image/jpeg", ["jpg", "jpeg"]], ["image/webp", ["webp"]],
  ["audio/mpeg", ["mp3"]], ["audio/mp3", ["mp3"]], ["audio/opus", ["opus"]],
  ["audio/ogg", ["ogg", "opus"]], ["audio/aac", ["aac"]], ["audio/flac", ["flac"]],
  ["audio/wav", ["wav"]], ["audio/x-wav", ["wav"]], ["audio/pcm", ["pcm"]],
  ["audio/L16", ["pcm"]], ["application/octet-stream", ["pcm"]],
]);

export function generationSelection(config, kind) {
  const selected = config?.generation?.[kind];
  return selected && typeof selected.provider === "string" && selected.provider.trim() &&
    typeof selected.model === "string" && selected.model.trim() ? selected : null;
}

function checkFilename(value) {
  if (value === undefined) return;
  if (typeof value !== "string" || !value || value.length > 180 ||
      /[<>:"/\\|?*\x00-\x1f]/.test(value) || /[. ]$/.test(value) || value.startsWith(".") ||
      /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(value))
    throw new Error("output_filename must be a plain filename without a directory or reserved characters");
}

function checkResult(item, kind) {
  const extensions = mimeExtensions.get(item?.mimeType);
  const extension = String(item?.extension || "").replace(/^\./, "").toLowerCase();
  if (!extensions?.includes(extension) || (kind === "image" ? !item.mimeType.startsWith("image/") : item.mimeType.startsWith("image/")))
    throw new Error("Generation gateway returned an unsupported media format");
  if (typeof item.data !== "string" || !item.data.length || item.data.length > 90 * 1024 * 1024 ||
      item.data.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(item.data))
    throw new Error("Generation gateway returned invalid or oversized media data");
  return {data: Buffer.from(item.data, "base64"), extension, extensions};
}

export function createGenerationExtension({getConfig, fetchImpl = globalThis.fetch} = {}) {
  return pi => {
    for (const [kind, name, parameters] of [
      ["image", "image_gen", Type.Object({prompt: Type.String({minLength: 1, maxLength: 32000}),
        size: optionalString(64), count: Type.Optional(Type.Integer({minimum: 1, maximum: 10})),
        format: formats(["png", "jpeg", "webp"]), output_filename: filename})],
      ["speech", "voice_gen", Type.Object({text: Type.String({minLength: 1, maxLength: 32000}),
        voice: optionalString(120), format: formats(["mp3", "opus", "aac", "flac", "wav", "pcm"]),
        speed: Type.Optional(Type.Number({minimum: 0.25, maximum: 4})), output_filename: filename})],
    ]) {
      const selection = generationSelection(getConfig(), kind);
      if (!selection) continue;
      pi.registerTool({name, label: kind === "image" ? "生成图片" : "生成语音", exposure: "direct",
        description: `Generate ${kind === "image" ? "images" : "speech"} with the configured ${selection.provider} / ${selection.model}. Sends the prompt or text to that provider after user confirmation. Saves new files in the current workspace without overwriting existing files, and displays them in chat. Optional output_filename must be a plain filename. Omitted options use Umeko's generation settings. Returns paths, never media bytes to the chat model.`,
        annotations: {readOnlyHint: false, destructiveHint: false}, parameters,
        async execute(id, params, signal, _update, ctx) {
          signal?.throwIfAborted();
          checkFilename(params.output_filename);
          const config = getConfig();
          if (!generationSelection(config, kind)) throw new Error("Generation provider is no longer configured");
          const cwd = await realpath(ctx.cwd);
          const {output_filename, ...overrides} = params;
          const suppliedExtension = extname(output_filename || "").slice(1).toLowerCase();
          const filenameFormat = suppliedExtension === "jpg" ? "jpeg" : suppliedExtension;
          const supportedFormats = kind === "image" ? ["png", "jpeg", "webp"] : ["mp3", "opus", "aac", "flac", "wav", "pcm"];
          if (suppliedExtension && !supportedFormats.includes(filenameFormat))
            throw new Error("output_filename extension is not supported for this media type");
          if (suppliedExtension && overrides.format && filenameFormat !== overrides.format)
            throw new Error("output_filename extension must match format");
          if (suppliedExtension && !overrides.format) overrides.format = filenameFormat;
          const response = await fetchImpl(new URL("umeko/generate", config.gateway), {
            method: "POST", headers: {"Authorization": `Bearer ${config.token}`, "Content-Type": "application/json"},
            body: JSON.stringify({kind, ...overrides}), signal,
          });
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error?.message || error.message || `Generation failed (HTTP ${response.status})`);
          }
          const result = await response.json();
          signal?.throwIfAborted();
          if (!Array.isArray(result.items) || !result.items.length || result.items.length > (kind === "image" ? 10 : 1))
            throw new Error("Generation gateway returned no valid media items");
          const decoded = result.items.map(item => checkResult(item, kind));
          if (suppliedExtension && decoded.some(item => !item.extensions.includes(suppliedExtension)))
            throw new Error("output_filename extension does not match the generated media format");
          const stem = output_filename ? basename(output_filename, extname(output_filename)) : `${kind === "image" ? "image" : "voice"}-${Date.now()}`;
          const paths = [], items = [];
          try {
            for (const item of decoded) {
              signal?.throwIfAborted();
              const extension = suppliedExtension || item.extension;
              let path, handle;
              for (let suffix = 0; suffix < 10000; suffix++) {
                path = join(cwd, `${stem}${suffix ? `-${suffix + 1}` : ""}.${extension}`);
                try { handle = await open(path, "wx"); break; }
                catch (error) { if (error.code !== "EEXIST") throw error; }
              }
              if (!handle) throw new Error("No unused output filename is available");
              paths.push(path);
              try { await handle.writeFile(item.data, {signal}); }
              finally { await handle.close(); }
              items.push({path, name: basename(path), title: basename(path), caption: "",
                kind: kind === "image" ? "image" : "file", bytes: item.data.length});
            }
            signal?.throwIfAborted();
            return deliverChatboxItems(pi, id, items, {paths, provider: result.provider, model: result.model});
          } catch (error) {
            await Promise.all(paths.map(path => unlink(path).catch(() => {})));
            throw error;
          }
        },
      });
    }
  };
}
