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
  ["video/mp4", ["mp4"]],
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
  const expectedMedia = kind === "image" ? item?.mimeType?.startsWith("image/") : kind === "video" ? item?.mimeType === "video/mp4" :
    item?.mimeType?.startsWith("audio/") || item?.mimeType === "application/octet-stream";
  if (!extensions?.includes(extension) || !expectedMedia)
    throw new Error("Generation gateway returned an unsupported media format");
  if (typeof item.data !== "string" || !item.data.length || item.data.length > 90 * 1024 * 1024 ||
      item.data.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(item.data))
    throw new Error("Generation gateway returned invalid or oversized media data");
  return {data: Buffer.from(item.data, "base64"), extension, extensions};
}

function videoProgress(event, language) {
  const status = String(event.status || "").toLowerCase();
  const state = ["queued", "pending"].includes(status) ? 0 :
    ["completed", "succeeded", "done"].includes(status) ? 2 :
    ["failed", "error", "cancelled", "canceled"].includes(status) ? 3 : 1;
  const label = (language === "zh" ? ["排队中", "生成中", "已完成", "失败"] :
    ["Queued", "Generating", "Completed", "Failed"])[state];
  return {content: [{type: "text", text: `${label}${event.progress === undefined || event.progress === null ? "" : ` ${event.progress}%`}`}],
    details: {video: {id: event.id, status: event.status, progress: event.progress}}};
}

async function readVideoResult(response, signal, onUpdate, language) {
  if (!response.body) throw new Error("Generation gateway returned no video stream");
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "", result, complete = false, rejectAbort;
  const aborted = new Promise((_, reject) => { rejectAbort = reject; });
  const cancel = () => {
    rejectAbort(signal.reason || new Error("Video generation cancelled"));
    Promise.resolve(reader.cancel(signal.reason)).catch(() => {});
  };
  signal?.addEventListener("abort", cancel, {once: true});
  const consume = line => {
    signal?.throwIfAborted();
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (result) throw new Error("Generation gateway returned data after the video result");
    if (event.type === "progress") onUpdate?.(videoProgress(event, language));
    else if (event.type === "result") result = event.result;
    else if (event.type === "error") throw new Error(event.error?.message || "Video generation failed");
    else throw new Error("Generation gateway returned an unknown video event");
    signal?.throwIfAborted();
  };
  try {
    signal?.throwIfAborted();
    for (;;) {
      signal?.throwIfAborted();
      const {done, value} = await Promise.race([reader.read(), aborted]);
      signal?.throwIfAborted();
      buffer += decoder.decode(value, {stream: !done});
      let end;
      while ((end = buffer.indexOf("\n")) >= 0) {
        consume(buffer.slice(0, end)); buffer = buffer.slice(end + 1);
      }
      if (done) { if (buffer.trim()) consume(buffer); complete = true; break; }
    }
    signal?.throwIfAborted();
    if (!result) throw new Error("Generation gateway ended without a video result");
    return result;
  } finally {
    signal?.removeEventListener("abort", cancel);
    if (!complete) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
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
      ["video", "video_gen", Type.Object({prompt: Type.String({minLength: 1, maxLength: 32000}),
        seconds: Type.Optional(Type.String({pattern: "^[1-9][0-9]*$"})),
        size: Type.Optional(Type.String({pattern: "^[1-9][0-9]*x[1-9][0-9]*$"})), output_filename: filename})],
    ]) {
      const selection = generationSelection(getConfig(), kind);
      if (!selection) continue;
      pi.registerTool({name, label: kind === "image" ? "生成图片" : kind === "video" ? "生成视频" : "生成语音", exposure: "direct",
        description: `Generate ${kind === "image" ? "images" : kind === "video" ? "video" : "speech"} with the configured ${selection.provider} / ${selection.model}. Sends the prompt or text to that provider after user confirmation. Saves new files in the current workspace without overwriting existing files, and displays them in chat. Optional output_filename must be a plain filename.${kind === "video" ? " Video output is MP4; seconds is a positive integer string and size is WIDTHxHEIGHT. Progress is reported while generation runs." : ""} Omitted options use Umeko's generation settings. Returns paths, never media bytes to the chat model.`,
        annotations: {readOnlyHint: false, destructiveHint: false}, parameters,
        async execute(id, params, signal, onUpdate, ctx) {
          signal?.throwIfAborted();
          checkFilename(params.output_filename);
          if (kind === "video") {
            if (typeof params.prompt !== "string" || !params.prompt.trim() || params.prompt.length > 32000)
              throw new Error("prompt must be a nonempty string of at most 32000 characters");
            if (params.seconds !== undefined && (typeof params.seconds !== "string" || !/^[1-9][0-9]*$/.test(params.seconds)))
              throw new Error("seconds must be a positive integer string");
            if (params.size !== undefined && (typeof params.size !== "string" || !/^[1-9][0-9]*x[1-9][0-9]*$/.test(params.size)))
              throw new Error("size must be WIDTHxHEIGHT with positive integer dimensions");
          }
          const config = getConfig();
          if (!generationSelection(config, kind)) throw new Error("Generation provider is no longer configured");
          const cwd = await realpath(ctx.cwd);
          const {output_filename, ...overrides} = params;
          const suppliedExtension = extname(output_filename || "").slice(1).toLowerCase();
          const filenameFormat = suppliedExtension === "jpg" ? "jpeg" : suppliedExtension;
          const supportedFormats = kind === "image" ? ["png", "jpeg", "webp"] : kind === "video" ? ["mp4"] : ["mp3", "opus", "aac", "flac", "wav", "pcm"];
          if (suppliedExtension && !supportedFormats.includes(filenameFormat))
            throw new Error("output_filename extension is not supported for this media type");
          if (suppliedExtension && overrides.format && filenameFormat !== overrides.format)
            throw new Error("output_filename extension must match format");
          if (kind !== "video" && suppliedExtension && !overrides.format) overrides.format = filenameFormat;
          signal?.throwIfAborted();
          const response = await fetchImpl(new URL("umeko/generate", config.gateway), {
            method: "POST", headers: {"Authorization": `Bearer ${config.token}`, "Content-Type": "application/json"},
            body: JSON.stringify({kind, ...overrides}), signal,
          });
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error?.message || error.message || `Generation failed (HTTP ${response.status})`);
          }
          signal?.throwIfAborted();
          const result = kind === "video" ? await readVideoResult(response, signal, onUpdate, config.language) : await response.json();
          signal?.throwIfAborted();
          if (!Array.isArray(result?.items) || !result.items.length || result.items.length > (kind === "image" ? 10 : 1))
            throw new Error("Generation gateway returned no valid media items");
          const decoded = result.items.map(item => checkResult(item, kind));
          if (suppliedExtension && decoded.some(item => !item.extensions.includes(suppliedExtension)))
            throw new Error("output_filename extension does not match the generated media format");
          const stem = output_filename ? basename(output_filename, extname(output_filename)) : `${kind === "image" ? "image" : kind === "video" ? "video" : "voice"}-${Date.now()}`;
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
