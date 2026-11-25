import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../", import.meta.url));
const executable = join(repo, "runtime/releases/coding-1.5.2/bridge.mjs");
const reviewer = "child-0123456789abcdef0123456789abcdef";

test("a Cowork task delegates only to its chosen subagent with its own Pi tools and skill", {timeout: 30000}, async t => {
  assert.deepEqual(readFileSync(executable), readFileSync(join(repo, "runtime/bridge.mjs")), "Run prepare_runtime.py");
  const workspace = mkdtempSync(join(tmpdir(), "umeko-cowork-child-"));
  const agentDir = join(workspace, "agent");
  const ordinary = join(agentDir, "skills/ordinary");
  const child = join(workspace, "child-reference");
  mkdirSync(ordinary, {recursive:true});
  writeFileSync(join(ordinary, "SKILL.md"), "---\nname: ordinary\ndescription: Standard agent only.\n---\nIgnore in cowork.\n");
  mkdirSync(child);
  const skill = join(child, "SKILL.md");
  writeFileSync(skill, "---\nname: child-reference\ndescription: Skill for this specific reviewer.\n---\nCheck the source files.\n");
  const mcpDir = join(workspace, "cowork-mcp");
  const imported = spawnSync(process.execPath, [executable, "--cowork-mcp-tools"], {
    input: JSON.stringify({cwd:workspace, agentDir, scopeDir:mcpDir, text:JSON.stringify({mcpServers:{
      notes:{command:process.execPath,args:[join(repo,"tests/fixtures/cowork-mcp-server.mjs")]},
    }})}), encoding:"utf8", timeout:15000, windowsHide:true,
  });
  assert.equal(imported.status, 0, imported.stdout + imported.stderr);
  const mcp = JSON.parse(imported.stdout).servers[0];
  assert.equal(mcp.state, "connected");
  const parentTool = mcp.tools.find(tool => tool.label === "parent-note");
  const childTool = mcp.tools.find(tool => tool.label === "child-note");
  const parents = [], children = [], events = [];
  const server = createServer(async (request, response) => {
    let json = "";
    for await (const data of request) json += data;
    const body = JSON.parse(json);
    const prompt = body.messages.filter(row => row.role === "system" || row.role === "developer").map(row => row.content).join("\n");
    const isChild = prompt.includes("REVIEWER_SCOPE");
    const calls = isChild ? children : parents;
    calls.push({prompt, model:body.model, tools:body.tools?.map(tool => tool.function.name) || [], messages:body.messages});
    const chunk = (delta, finish_reason = null) => `data: ${JSON.stringify({id:"fixture",object:"chat.completion.chunk",
      created:1,model:body.model,choices:[{index:0,delta,finish_reason}]})}\n\n`;
    response.writeHead(200, {"Content-Type":"text/event-stream"});
    response.write(chunk({role:"assistant"}));
    if (isChild && children.length === 1) {
      response.end(chunk({tool_calls:[{index:0,id:"child-mcp-call",type:"function",function:{name:childTool.name,arguments:"{}"}}]}) + chunk({}, "tool_calls") + "data: [DONE]\n\n");
    } else if (isChild || parents.length > 2) {
      response.end(chunk({content:isChild ? "CHILD_OK" : "PARENT_OK"}) + chunk({}, "stop") + "data: [DONE]\n\n");
    } else {
      const subagent_type = parents.length === 1 ? "general-purpose" : reviewer;
      response.end(chunk({tool_calls:[{index:0,id:"delegate-" + parents.length,type:"function",function:{name:"subagent",
        arguments:JSON.stringify({subagent_type,prompt:"Verify the document.",description:"Review source",
          inherit_context:true,run_in_background:false})}}]}) + chunk({}, "tool_calls") + "data: [DONE]\n\n");
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const processHandle = spawn(process.execPath, [executable], {cwd:workspace, stdio:["pipe","pipe","pipe"],
    env:{...process.env, PI_CODING_AGENT_DIR:agentDir}, windowsHide:true});
  let stderr = "";
  processHandle.stderr.on("data", data => { stderr = (stderr + data).slice(-2500); });
  t.after(async () => {
    if (processHandle.exitCode === null && processHandle.signalCode === null) {
      const stopped = once(processHandle, "exit");
      processHandle.kill();
      await stopped;
    }
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    rmSync(workspace, {recursive:true, force:true});
  });
  processHandle.stdin.write(JSON.stringify({
    type:"prompt", text:"PRIVATE_PARENT_MESSAGE", gateway:`http://127.0.0.1:${server.address().port}/`, token:"fixture",
    model:"fake", models:[{id:"fake",contextWindow:128000}, {id:"fixture-child",contextWindow:128000}], workspace, defaultCwd:workspace, agentDir,
    sessionDir:join(workspace,"sessions"), initialSessionTitle:"Prepared review", agent:{safeMode:false, instructions:"PARENT_SCOPE"},
    cowork:{allowedTools:[parentTool.name], toolOwners:{[parentTool.name]:parentTool.owner}, skillPaths:[],mcpDir, subagents:[{
      id:reviewer,name:"Document reviewer",description:"Check the document",prompt:"REVIEWER_SCOPE",
      context:"files", tools:["grep",childTool.name], toolOwners:{[childTool.name]:childTool.owner}, skillPaths:[skill], model:"fixture-child", character:"komari",
    }]},
  }) + "\n");
  const lines = createInterface({input:processHandle.stdout});
  const timeout = AbortSignal.timeout(20000);
  const deadline = new Promise((_, reject) => timeout.addEventListener("abort", () =>
    reject(new Error(JSON.stringify({stderr,events:events.slice(-6)}))), {once:true}));
  await Promise.race([deadline, (async () => {
    for await (const line of lines) {
      if (!line.startsWith("{")) continue;
      const event = JSON.parse(line);
      events.push(event);
      if (event.type === "done" && event.action === "prompt") return;
      if (event.type === "error") throw new Error(JSON.stringify(event) + stderr);
    }
    throw new Error("Bridge exited: " + stderr);
  })()]);
  assert.equal(children.length, 2, JSON.stringify(events.filter(event => event.type === "tool").slice(-4)));
  assert.match(parents[0].prompt, /PARENT_SCOPE/);
  assert.ok(parents[0].tools.includes("subagent"));
  assert.ok(parents[0].tools.includes(parentTool.name) && !parents[0].tools.includes(childTool.name), parents[0].tools);
  assert.match(JSON.stringify(parents[1].messages), /Select a subagent enabled for this coworker/);
  assert.doesNotMatch(parents[0].prompt, /child-reference/);
  assert.match(children[0].prompt, /child-reference/);
  assert.equal(children[0].model, "fixture-child");
  assert.doesNotMatch(children[0].prompt, /Standard agent only|PARENT_SCOPE/);
  assert.doesNotMatch(JSON.stringify(children[0].messages), /PRIVATE_PARENT_MESSAGE/);
  assert.ok(children[0].tools.includes("grep") && children[0].tools.includes("read"), children[0].tools);
  assert.ok(!children[0].tools.includes("write") && !children[0].tools.includes("subagent"), children[0].tools);
  assert.ok(children[0].tools.includes(childTool.name) && !children[0].tools.includes(parentTool.name), children[0].tools);
  assert.match(JSON.stringify(children[1].messages), /MCP note: child-note/);
  assert.ok(events.some(event => event.subagent?.profileName === "Document reviewer" && event.subagent.character === "komari" && event.subagent.result.includes("CHILD_OK")));
  const session = events.find(event => event.session?.file)?.session;
  assert.equal(session?.title, "Prepared review");
  const entries = readFileSync(session.file, "utf8").trim().split("\n").map(line => JSON.parse(line));
  assert.ok(entries.some(entry => entry.type === "session_info" && entry.name === "Prepared review"));
});
