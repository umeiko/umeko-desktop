import { accessSync, constants, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";

export function recentImageLimit(value = 3) {
  return Number.isSafeInteger(value) ? Math.max(1, value) : 3;
}

// Adapted from anthropic-quickstarts' _maybe_filter_to_n_most_recent_images.
// Round removal UP, not down: the provider's limit is a hard ceiling. With
// K >= 2, pairs of old images leave the same prefix in place for two additions.
export function filterRecentImages(messages, { limit = 3, resolvePath } = {}) {
  const eligible = message => ["user", "toolResult"].includes(message.role) && Array.isArray(message.content);
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
      const path = resolvePath(message, block, index, messageIndex);
      // Never emit a reopen instruction for a missing or unreadable file.
      accessSync(path, constants.R_OK);
      remove--;
      return { type: "text", text: `[Image removed from context to save space. Use read on ${JSON.stringify(path)} to see it again.]` };
    }) };
  });
}

const signature = message => JSON.stringify([message.role, message.timestamp, message.toolCallId]);
const safeName = value => String(value).replace(/[^a-zA-Z0-9_-]/g, "_");
const suffixes = { "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp" };

export function createRecentImagesExtension({ getLimit = () => 3 } = {}) {
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
      return { messages: filterRecentImages(event.messages, {
        limit: getLimit(),
        resolvePath(message, block, index, messageIndex) {
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
        },
      }) };
    });
  };
}
