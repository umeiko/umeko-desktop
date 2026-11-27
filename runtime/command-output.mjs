// Head/tail collection and output text adapted from OpenAI Codex rust-v0.172.0:
// codex-rs/utils/head-tail-buffer/src/lib.rs, utils/string/src/truncate.rs and
// utils/output-truncation/src/lib.rs. Apache-2.0, see licenses/codex-NOTICE.txt.
export const previewBytes = 50 * 1024;
const previewLines = 2_000;

export function outputWindow() {
  let head = Buffer.alloc(0), tail = head, bytes = 0, newlines = 0, endsWithNewline = false;
  return {
    append(text) {
      if (!text) return;
      const buffer = Buffer.from(text);
      bytes += buffer.length;
      if (head.length < previewBytes) {
        head = Buffer.concat([head, buffer.subarray(0, previewBytes - head.length)]);
      }
      tail = Buffer.concat([tail.subarray(Math.max(0, tail.length + buffer.length - previewBytes)),
        buffer.subarray(Math.max(0, buffer.length - previewBytes))]);
      for (let at = text.indexOf("\n"); at !== -1; at = text.indexOf("\n", at + 1)) newlines++;
      endsWithNewline = text.endsWith("\n");
    },
    get value() { return { head, tail, bytes, newlines, endsWithNewline }; },
  };
}

function headBytes(buffer, limit) {
  let end = Math.min(limit, buffer.length);
  while (end > 0 && (buffer[end] & 0xc0) === 0x80) end--;
  return buffer.subarray(0, end).toString("utf8");
}

function tailBytes(buffer, limit) {
  let start = Math.max(0, buffer.length - limit);
  while (start < buffer.length && (buffer[start] & 0xc0) === 0x80) start++;
  return buffer.subarray(start).toString("utf8");
}

export function formatCommandOutput(stdout, stderr, details, job, rawBytes) {
  const both = stdout.bytes > 0 && stderr.bytes > 0;
  const separator = Buffer.from(both && !stdout.endsWithNewline ? "\n" : "");
  const bytes = stdout.bytes + stderr.bytes + separator.length;
  const last = stderr.bytes > 0 ? stderr : stdout;
  const lines = stdout.newlines + stderr.newlines + separator.length +
    (bytes > 0 && !last.endsWithNewline ? 1 : 0);
  const head = Buffer.concat([stdout.head, separator, stderr.head]);
  const suffix = details.length ? "\n\n" + details.join("\n") : "";
  const detailLines = suffix.split("\n").length;
  if (bytes + Buffer.byteLength(suffix) <= previewBytes && lines + detailLines <= previewLines) {
    return { text: head.toString("utf8") + suffix };
  }
  const tail = Buffer.concat([stdout.tail, separator, stderr.tail]);
  const tokens = Math.ceil(bytes / 4);
  const intro = `Warning: truncated output (original token count: ${tokens})\nTotal output lines: ${lines}\nOriginal output size: ${rawBytes} bytes\n\n`;
  const logs = [stdout.bytes && `Full stdout log: ${job.stdoutPath}`, stderr.bytes && `Full stderr log: ${job.stderrPath}`]
    .filter(Boolean).join("\n");
  const footer = "\n\n" + logs + suffix;
  const marker = omitted => `\n…${omitted} tokens truncated…\n`;
  const byteBudget = Math.max(0, Math.floor((previewBytes - Buffer.byteLength(intro + marker(tokens) + footer)) / 2));
  const lineBudget = Math.max(1, Math.floor((previewLines - detailLines - 10) / 2));
  const start = headBytes(head, byteBudget).split("\n").slice(0, lineBudget).join("\n");
  const end = tailBytes(tail, byteBudget).split("\n").slice(-lineBudget).join("\n");
  const omitted = Math.ceil(Math.max(0, bytes - Buffer.byteLength(start) - Buffer.byteLength(end)) / 4);
  return { text: intro + start + marker(omitted) + end + footer, truncated: true,
    outputPath: stdout.bytes ? job.stdoutPath : job.stderrPath };
}
