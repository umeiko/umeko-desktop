import { execFile } from "node:child_process";
import { stat } from "node:fs/promises";
import { extname, resolve } from "node:path";
import { promisify } from "node:util";
import { Type } from "typebox";
import { sandboxFailure } from "./windows-sandbox.mjs";

const execute = promisify(execFile);
const pathParameter = Type.String({minLength: 1, maxLength: 4096});
const OCR_FORMATS = new Set([".png", ".jpg", ".jpeg", ".heic", ".webp", ".bmp", ".gif", ".tif", ".tiff"]);
const PDF_FORMATS = new Set([".pdf"]);

const OCR_SCRIPT = `
ObjC.import("Foundation");
ObjC.import("Vision");
function run(args) {
  const url = $.NSURL.fileURLWithPath(args[0]);
  const handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $.NSDictionary.dictionary);
  const request = $.VNRecognizeTextRequest.alloc.init;
  request.recognitionLevel = 1;
  request.recognitionLanguages = $(["zh-Hans", "zh-Hant", "en-US"]);
  request.automaticallyDetectsLanguage = true;
  if (!handler.performRequestsError($([request]), Ref())) throw Error("Image recognition failed");
  const lines = [];
  const results = request.results;
  for (let i = 0; i < results.count; i++) {
    const candidate = results.objectAtIndex(i).topCandidates(1).firstObject;
    const text = ObjC.unwrap(candidate.string);
    if (text) lines.push(text);
  }
  return lines.join("\\n");
}
`;
const PDF_SCRIPT = `
ObjC.import("Foundation");
ObjC.import("PDFKit");
function run(args) {
  const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(args[0]));
  const count = Number(doc.pageCount);
  if (doc.isLocked || !Number.isInteger(count) || count < 1) throw Error("Could not open PDF");
  const start = Number(args[1]);
  const text = ["Pages: " + count];
  for (let index = start - 1; index < Math.min(start - 1 + Number(args[2]), count); index++) {
    const page = ObjC.unwrap(doc.pageAtIndex(index).string) || "";
    text.push("--- Page " + (index + 1) + " ---\\n" + page.slice(0, 12000));
  }
  return text.join("\\n\\n");
}
`;

async function sourceFile(path, cwd, extensions) {
  const target = resolve(cwd, path);
  const info = await stat(target);
  if (!info.isFile() || !extensions.has(extname(target).toLowerCase())) throw new Error("Select a file in a supported format.");
  if (info.size > 80 * 1024 * 1024) throw new Error("The selected file exceeds 80 MiB.");
  return target;
}

async function run(command, args, signal, setupHint, cwd, prepareCommand) {
  const launch = await prepareCommand?.({ file: command, args, cwd }, signal) || { file: command, args };
  try {
    const {stdout} = await execute(launch.file, launch.args, {signal, timeout: 30000, maxBuffer: 512 * 1024,
      env: launch.env, cwd: launch.cwd, windowsHide: true});
    return stdout.trim();
  } catch (error) {
    signal?.throwIfAborted();
    if (error.code === "ENOENT") throw new Error(setupHint);
    if (error.killed) throw new Error("Local extraction timed out.");
    if (launch.level && launch.level !== "off") throw new Error(sandboxFailure(launch.level, launch.allowNetwork, error.stderr));
    throw new Error("Local extraction failed for this file.");
  }
}

export function registerCoworkLocalTools(pi, allowed, prepareCommand) {
  if (allowed.has("ocr_image")) {
    pi.registerTool({name: "ocr_image", label: "提取图片文字", exposure: "direct", annotations: {readOnlyHint: true},
      description: "Extract text from a local image using Apple Vision on macOS or Tesseract elsewhere. Use an explicitly attached image. Languages is an optional Tesseract language list, such as chi_sim+eng.",
      parameters: Type.Object({path: pathParameter, languages: Type.Optional(Type.String({pattern: "^[a-z_]+(?:\\+[a-z_]+){0,3}$", maxLength: 64}))}),
      async execute(_id, {path, languages}, signal, _update, ctx) {
        const file = await sourceFile(path, ctx.cwd, OCR_FORMATS);
        const text = process.platform === "darwin" ?
          await run("/usr/bin/osascript", ["-l", "JavaScript", "-e", OCR_SCRIPT, file], signal, "Use auxiliary vision if Apple Vision is unavailable.", ctx.cwd, prepareCommand) :
          await run("tesseract", [file, "stdout", "-l", languages || "eng"], signal, "Install Tesseract or use auxiliary vision.", ctx.cwd, prepareCommand);
        return {content: [{type: "text", text: text.slice(0, 20000) || "No readable text found."}]};
      },
    });
  }
  if (allowed.has("read_pdf_text")) {
    pi.registerTool({name: "read_pdf_text", label: "读取 PDF 文字", exposure: "direct", annotations: {readOnlyHint: true},
      description: "Extract a range of text pages from a local PDF using PDFKit on macOS or Poppler elsewhere. Start at page 1. Scanned pages may need OCR.",
      parameters: Type.Object({path: pathParameter, start_page: Type.Optional(Type.Integer({minimum: 1, maximum: 100000})),
        pages: Type.Optional(Type.Integer({minimum: 1, maximum: 8}))}),
      async execute(_id, {path, start_page = 1, pages = 4}, signal, _update, ctx) {
        const file = await sourceFile(path, ctx.cwd, PDF_FORMATS);
        let text;
        if (process.platform === "darwin") {
          text = await run("/usr/bin/osascript", ["-l", "JavaScript", "-e", PDF_SCRIPT, file, String(start_page), String(pages)],
            signal, "Use the PDF Skill if PDFKit is unavailable.", ctx.cwd, prepareCommand);
        } else {
          const output = await run("pdftotext", ["-layout", "-f", String(start_page), "-l", String(start_page + pages - 1), file, "-"],
            signal, "Install Poppler or use the PDF Skill.", ctx.cwd, prepareCommand);
          text = output.split("\f").filter((page, index, all) => page.trim() || index < all.length - 1)
            .map((page, index) => "--- Page " + (start_page + index) + " ---\n" + page.trim()).join("\n\n");
        }
        return {content: [{type: "text", text: text.slice(0, 28000) || "No extractable text found."}]};
      },
    });
  }
}
