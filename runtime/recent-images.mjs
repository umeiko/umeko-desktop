import { accessSync, constants, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { createHash } from "node:crypto";

const IMAGE_BYTES = 256 * 1024; // Base64 bytes, not the decoded file size.
const REQUEST_IMAGE_BYTES = 512 * 1024;
const MAX_RESIZE_INPUT_BYTES = 12 * 1024 * 1024;
const eligible = message => ["user", "toolResult", "custom"].includes(message.role) && Array.isArray(message.content);

function imageReference(message, block, index, messageIndex, resolvePath) {
  try {
    const path = resolvePath(message, block, index, messageIndex);
    accessSync(path, constants.R_OK);
    return { type: "text", text: `[Image removed from context to save space. Use read on ${JSON.stringify(path)} to see it again.]` };
  } catch {
    return { type: "text", text: "[Image omitted from model context to save space. The original is still in the chat.]" };
  }
}

export function recentImageLimit(value = 3) {
  return Number.isSafeInteger(value) ? Math.max(1, value) : 3;
}

// Adapted from anthropic-quickstarts' _maybe_filter_to_n_most_recent_images.
// Round removal UP, not down: the provider's limit is a hard ceiling. With
// K >= 2, pairs of old images leave the same prefix in place for two additions.
export function filterRecentImages(messages, { limit = 3, resolvePath } = {}) {
  const count = messages.reduce((total, message) => total + (eligible(message)
    ? message.content.filter(block => block.type === "image").length : 0), 0);
  const keep = recentImageLimit(limit);
  if (count <= keep) return messages;
  const chunk = Math.min(2, keep);
  let remove = Math.min(count - 1, Math.ceil((count - keep) / chunk) * chunk);
  return messages.map((message, messageIndex) => {
    if (!eligible(message) || !remove) return message;
    return { ...message, content: message.content.map((block, index) => {
      if (block.type !== "image" || !remove) return block;
      remove--;
      return imageReference(message, block, index, messageIndex, resolvePath);
    }) };
  });
}

const signature = message => JSON.stringify([message.role, message.timestamp, message.toolCallId]);
const safeName = value => String(value).replace(/[^a-zA-Z0-9_-]/g, "_");
const suffixes = { "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp" };

async function fitImageBudget(messages, original, resolvePath, resize) {
  const result = messages.slice();
  let remaining = REQUEST_IMAGE_BYTES;
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (!eligible(message)) continue;
    let content;
    for (let j = message.content.length - 1; j >= 0; j--) {
      const block = message.content[j];
      if (block.type !== "image") continue;
      const projected = block.data.length <= IMAGE_BYTES ? block : remaining >= IMAGE_BYTES ? await resize(block) : null;
      const fits = projected && projected.data.length <= remaining;
      if (fits) {
        remaining -= projected.data.length;
        if (projected === block) continue;
      }
      content ??= message.content.slice();
      content[j] = fits ? projected : imageReference(original[i], block, j, i, resolvePath);
    }
    if (content) result[i] = { ...message, content };
  }
  return { messages: result };
}

export function createRecentImagesExtension({ getLimit = () => 3, resizeImage } = {}) {
  const resizedImages = new Map();
  async function resize(block) {
    if (block.data.length > MAX_RESIZE_INPUT_BYTES) return null;
    const key = createHash("sha256").update(block.mimeType).update(block.data).digest("base64url");
    if (!resizedImages.has(key)) {
      let result;
      try {
        result = await resizeImage(Buffer.from(block.data, "base64"), block.mimeType, {
          maxWidth: 1024, maxHeight: 1024, maxBytes: IMAGE_BYTES, jpegQuality: 80
        });
      } catch { /* A malformed or unsupported image becomes a file reference. */ }
      resizedImages.set(key, result?.data.length <= IMAGE_BYTES ? { data: result.data, mimeType: result.mimeType } : null);
      if (resizedImages.size > 12) resizedImages.delete(resizedImages.keys().next().value);
    }
    const resized = resizedImages.get(key);
    return resized && { ...block, ...resized };
  }
  return pi => {
    pi.on("context", (event, ctx) => {
      const entries = ctx.sessionManager.getBranch();
      const bySignature = new Map(), calls = new Map();
      for (const entry of entries) {
        if (entry.type !== "message") continue;
        const key = signature(entry.message);
        if (!bySignature.has(key)) bySignature.set(key, []);
        bySignature.get(key).push(entry.id);
        if (entry.message.role === "assistant") {
          for (const block of entry.message.content || []) {
            if (block.type === "toolCall" && block.name === "read" && typeof block.arguments?.path === "string")
              calls.set(block.id, block.arguments.path);
          }
        }
      }
      const occurrences = new Map();
      const ids = event.messages.map((message, index) => {
        const key = signature(message), occurrence = occurrences.get(key) || 0;
        occurrences.set(key, occurrence + 1);
        return bySignature.get(key)?.[occurrence] || `pending-${safeName(key)}-${index}`;
      });
      const sessionFile = ctx.sessionManager.getSessionFile();
      const directory = sessionFile ? join(dirname(sessionFile), basename(sessionFile) + ".images")
        : join(ctx.sessionManager.getSessionDir(), safeName(ctx.sessionManager.getSessionId()) + ".images");
      function resolvePath(message, block, index, messageIndex) {
        let original;
        if (message.role === "toolResult") original = calls.get(message.toolCallId);
        else {
          const paths = message.content.filter(item => item.type === "text")
            .flatMap(item => [...item.text.matchAll(/^- image: (.+)$/gm)].map(match => match[1].trimEnd()));
          const imageIndex = message.content.slice(0, index).filter(item => item.type === "image").length;
          original = paths[imageIndex];
        }
        if (original) {
          const path = resolve(ctx.cwd, original);
          try { accessSync(path, constants.R_OK); return path; } catch { /* Preserve the session's original bytes below. */ }
        }
        mkdirSync(directory, { recursive: true });
        const path = join(directory, `${safeName(ids[messageIndex])}-${index}${suffixes[block.mimeType] || ".png"}`);
        if (!existsSync(path)) writeFileSync(path, Buffer.from(block.data, "base64"), { flag: "wx" });
        return path;
      }
      const messages = filterRecentImages(event.messages, { limit: getLimit(), resolvePath });
      const imageBytes = messages.reduce((total, message) => total + (eligible(message) ? message.content.reduce(
        (bytes, block) => bytes + (block.type === "image" ? block.data.length : 0), 0) : 0), 0);
      if (!resizeImage || !ctx.model?.input?.includes("image") || imageBytes <= IMAGE_BYTES) return { messages };
      return fitImageBudget(messages, event.messages, resolvePath, resize);
    });
  };
}
