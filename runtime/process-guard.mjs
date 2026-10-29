// Lexical accident prevention, not a command sandbox. Pi's permission-gate
// example supplies the tool_call/block contract; these rules are Umeko's.
export const PROCESS_GUARD_MESSAGE = "Blocked: killing processes by name or in bulk can also stop Umeko and other work. Use background_job kill with your job ID, or a specific positive PID you started.";

export function blockedProcessCommand(command) {
  // Normalize shell quoting and escaped option prefixes, including Git Bash's
  // //IM spelling. This intentionally favors blocking an ambiguous kill.
  const text = String(command || "")
    // Common output/input redirects do not change which process is selected.
    // Leave substitutions or shell operators visible to the guard.
    .replace(/(?:^|\s)\d*(?:>>?|<<?)\s*(?:"[^"$`\n]*"|'[^'\n]*'|&[0-9-]+|[^\s;&|()"'$`]+)/g, " ")
    .replace(/["'`^]/g, "");
  const tokens = text.match(/[^\s;&|()]+|[;&|()]/g) || [];
  const executable = token => token.replace(/^.*[\\/]/, "").replace(/\.exe$/i, "").toLowerCase();
  const end = index => {
    let next = index + 1;
    while (next < tokens.length && !/^[;&|()]$/.test(tokens[next])) next++;
    return tokens.slice(index + 1, next);
  };
  const positive = value => /^[1-9]\d*$/.test(value || "");
  for (let i = 0; i < tokens.length; i++) {
    const name = executable(tokens[i]);
    const args = end(i), lower = args.map(arg => arg.toLowerCase());
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
      const prior = tokens.slice(0, i).join(" ");
      const pipedId = /(?:get-process|gps)\s+-id\s+[1-9]\d*(?:\s+-[a-z]+)*\s*\|\s*$/i.test(prior);
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
      else if (/^-(?:[1-9]|[12]\d|3[01]|sig[a-z]+|term|kill|int|hup)$/i.test(rest[0] || "")) rest.shift();
      if (rest[0] === "--") rest.shift();
      if (rest.length !== 1 || !positive(rest[0])) return PROCESS_GUARD_MESSAGE;
    }
    if (name === "wmic") {
      const statement = tokens.slice(i + 1).join(" ").split(/[;&|]/)[0].trim();
      if (/\bprocess\b.*\bdelete\b/i.test(statement) && !/^process where processid\s*=\s*[1-9]\d* delete$/i.test(statement)) return PROCESS_GUARD_MESSAGE;
    }
  }
  return undefined;
}

export function assertProcessCommandAllowed(command) {
  const reason = blockedProcessCommand(command);
  if (reason) throw new Error(reason);
}
