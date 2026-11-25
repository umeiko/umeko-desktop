import { createInterface } from 'node:readline';

const tools = ['parent-note', 'child-note'].map(name => ({
  name, description: 'Return a fixture note', inputSchema: {type: 'object'},
}));
const requests = createInterface({input: process.stdin});
for await (const line of requests) {
  const request = JSON.parse(line);
  if (!Object.hasOwn(request, 'id')) continue;
  let result = {};
  if (request.method === 'initialize') {
    result = {protocolVersion: request.params.protocolVersion, capabilities: {tools: {}},
              serverInfo: {name: 'Cowork MCP fixture', version: '1.0.0'}};
  } else if (request.method === 'tools/list') {
    result = {tools};
  } else if (request.method === 'tools/call') {
    result = {content: [{type: 'text', text: 'MCP note: ' + request.params.name}]};
  }
  process.stdout.write(JSON.stringify({jsonrpc: '2.0', id: request.id, result}) + '\n');
}
