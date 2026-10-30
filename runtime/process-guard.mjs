// Lexical accident prevention, not a command sandbox. Pi's permission-gate
// example supplies the tool_call/block contract; these rules are Umeko's.
// Tokenization is delegated to shell-quote 1.12.0 (MIT):
// https://github.com/ljharb/shell-quote/tree/v1.12.0
import parse from "shell-quote/parse.js";

export const PROCESS_GUARD_MESSAGE = "Blocked: killing processes by name or in bulk can also stop Umeko and other work. Use background_job kill with your job ID, or a specific positive PID you started.";

const executable = token => token.replace(/^.*[\\/]/, "").replace(/\.exe$/i, "").toLowerCase();
const boundaries = new Set(["|", "|&", ";", "&&", "||", "&", "(", ")", "<(", ">("]);
const redirects = new Set([">", ">>", "<", "<<", "<<-", "<<<", "<&", ">&", "&>", "&>>", ">|", "<>"]);

// shell-quote treats newlines as whitespace. Preserve actual command boundaries
// while keeping quoted text and escaped line continuations as arguments.
function logicalLines(text, escape, shell) {
  const lines=[],heredocs=[];let start=0,quote="",comment=false;
  for(let i=0;i<text.length;i++) {
    const char=text[i];
    if(comment) {
      if(char!=="\n")continue;
    } else {
      if(char===escape&&quote!=="'"){i++;continue;}
      if(quote){if(char===quote)quote="";continue;}
      if(char==='"'||char==="'"){quote=char;continue;}
      if(char==="#"&&shell!=="cmd"&&(i===0||/[\s;&|()]/.test(text[i-1])))comment=true;
      if(shell==="bash"&&char==="<"&&text[i+1]==="<"&&text[i+2]!=="<"&&text[i-1]!=="<") {
        const match=text.slice(i).match(/^<<(-?)[ \t]*(?:'([^'\r\n]+)'|"([^"\r\n]+)"|\\?([^\s;&|<>()]+))/);
        if(match)heredocs.push({delimiter:match[2]??match[3]??match[4],tabs:match[1]==="-"});
      }
      if(char!=="\n")continue;
    }
    lines.push(text.slice(start,i).replace(/\r$/,""));start=i+1;comment=false;
    // A here-document is input data, not additional executable positions.
    for(const doc of heredocs.splice(0)) {
      while(start<text.length) {
        const end=text.indexOf("\n",start),stop=end<0?text.length:end;
        let line=text.slice(start,stop).replace(/\r$/,"");if(doc.tabs)line=line.replace(/^\t+/,"");
        start=end<0?text.length:end+1;
        if(line===doc.delimiter)break;
      }
    }
    i=start-1;
  }
  lines.push(text.slice(start));return lines;
}

function commandSegments(command, shell) {
  // Keep variables symbolic: inspecting a command must not read the real env.
  // PowerShell/cmd use different escapes, notably for Windows path backslashes.
  const escape = shell === "powershell" ? "`" : shell === "cmd" ? "^" : "\\";
  const text = String(command || "").replace(/(^|\s)\d+(?=[<>])/g, "$1");
  const tokens = logicalLines(text, escape, shell).flatMap((line,index) => [
    ...(index ? [{op:";"}] : []), ...parse(line, name => `$${name}`, { escape }),
  ]);
  const commands = [];
  let words = [], separator, previous;
  function flush() {
    if (words.length) {
      commands.push({ words, pipedFrom: separator === "|" ? previous : undefined });
      previous = words;
    }
    words = [];
  }
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token && typeof token === "object" && boundaries.has(token.op)) {
      flush(); separator = token.op;
    } else if (token && typeof token === "object" && redirects.has(token.op)) {
      i++; // A redirection target is a filename/fd, never an executable.
    } else if (typeof token === "string") words.push(token);
    else if (token?.op === "glob") words.push(token.pattern);
  }
  flush();
  return commands;
}

const wrappers=new Set(["sudo","doas","env","nohup","time","exec","nice","xargs","command","builtin","then","do","else"]);
const optionValues={
  sudo:new Set(["-u","-g","-h","-p","-C","-T","-R","-D","-r","-t","--user","--group","--host","--prompt","--close-from","--command-timeout","--chroot","--chdir","--role","--type"]),
  doas:new Set(["-u","-C"]),env:new Set(["-u","--unset","-C","--chdir","-a","--argv0","-S","--split-string"]),
  nice:new Set(["-n","--adjustment"]),time:new Set(["-f","--format","-o","--output"]),exec:new Set(["-a"]),
  xargs:new Set(["-I","-L","-P","-n","-s","-a","--arg-file","--max-args","--replace","--max-procs","--max-lines","--max-chars"]),
};
function invocation(words) {
  let start=0;
  while(start<words.length) {
    if(/^[A-Za-z_]\w*=/.test(words[start])){start++;continue;}
    const name=executable(words[start]);
    if(!wrappers.has(name))break;
    start++;
    if(name==="command"&&["-v","-V"].includes(words[start]))return [];
    while(start<words.length&&words[start].startsWith("-")) {
      const flag=words[start++];
      if(flag==="--")break;
      if(["--help","--version"].includes(flag))return [];
      if(optionValues[name]?.has(flag))start++;
    }
  }
  return words.slice(start);
}

export function blockedProcessCommand(command, shell = "bash") {
  let commands;
  try { commands = commandSegments(command, shell); }
  catch { return undefined; } // This accident guard does not validate shell syntax.
  const positive = value => /^[1-9]\d*$/.test(value || "");
  for (const { words, pipedFrom } of commands) {
    const call=invocation(words);
    if (!call.length) continue;
    const name = executable(call[0]);
    const args = call.slice(1), lower = args.map(arg => arg.toLowerCase());
    let nested;
    if (["bash", "sh", "dash", "zsh", "ksh"].includes(name)) {
      const option = args.findIndex(arg => /^-[a-z]*c$/i.test(arg));
      if (option !== -1) nested = [args[option + 1], "bash"];
    } else if (["powershell", "pwsh"].includes(name)) {
      const option = lower.findIndex(arg => ["-command", "-c"].includes(arg));
      if (option !== -1) nested = [args.slice(option + 1).join(" "), "powershell"];
    } else if (name === "cmd") {
      const option = lower.findIndex(arg => ["/c", "/k"].includes(arg));
      if (option !== -1) nested = [args.slice(option + 1).join(" "), "cmd"];
    }
    if (nested && blockedProcessCommand(...nested)) return PROCESS_GUARD_MESSAGE;
    if (["pkill", "killall", "tskill"].includes(name)) return PROCESS_GUARD_MESSAGE;
    if (name === "taskkill") {
      let pids = 0;
      for (let n = 0; n < args.length; n++) {
        const option = lower[n].replace(/^\/\//, "/");
        if (option === "/pid" && positive(args[n + 1])) { pids++; n++; }
        else if (!["/f", "/t"].includes(option)) return PROCESS_GUARD_MESSAGE;
      }
      if (pids !== 1) return PROCESS_GUARD_MESSAGE;
    }
    if (name === "stop-process" || name === "spps") {
      // A pipeline may feed explicit IDs, but an image-name Get-Process may not.
      const pipedId = pipedFrom && ["get-process", "gps"].includes(executable(pipedFrom[0]))
        && pipedFrom.length === 3 && pipedFrom[1].toLowerCase() === "-id" && positive(pipedFrom[2]);
      let ids = 0;
      for (let n = 0; n < args.length; n++) {
        if (lower[n] === "-id" && positive(args[n + 1])) { ids++; n++; }
        else if (!["-force", "-passthru", "-erroraction", "silentlycontinue", "stop"].includes(lower[n])) return PROCESS_GUARD_MESSAGE;
      }
      if (!(ids === 1 && !pipedId || ids === 0 && pipedId)) return PROCESS_GUARD_MESSAGE;
    }
    if (name === "kill") {
      let rest = [...args];
      if (["-s", "--signal"].includes(rest[0])) rest.splice(0, 2);
      else if (/^-(?:[0-9]|[12]\d|3[01]|sig[a-z]+|term|kill|int|hup)$/i.test(rest[0] || "")) rest.shift();
      if (rest[0] === "--") rest.shift();
      if (rest.length !== 1 || !positive(rest[0])) return PROCESS_GUARD_MESSAGE;
    }
    if (name === "wmic") {
      const statement = args.join(" ").trim();
      if (/\bprocess\b.*\bdelete\b/i.test(statement) && !/^process where processid\s*=\s*[1-9]\d* delete$/i.test(statement)) return PROCESS_GUARD_MESSAGE;
    }
  }
  return undefined;
}

export function assertProcessCommandAllowed(command) {
  const reason = blockedProcessCommand(command);
  if (reason) throw new Error(reason);
}
