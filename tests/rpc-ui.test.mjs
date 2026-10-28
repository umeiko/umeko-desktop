import test from "node:test";
import assert from "node:assert/strict";
import { rpcCustom } from "../runtime/rpc-ui.mjs";

test("RPC custom returns undefined without invoking a terminal renderer", async () => {
  assert.equal(await rpcCustom(() => { throw new Error("terminal renderer invoked"); }), undefined);
});
