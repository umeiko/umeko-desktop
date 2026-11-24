import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import {
  listSshConfigHosts,
  loadSshConfigText,
  parseHostBlocks,
  resolveSshHost,
  splitValue,
} from "./remote-ssh-config.mjs";
import {
  isWindowsRemotePath,
  joinRemotePath,
  joinRemoteRel,
  nativePathFromUri,
  normalizeRemotePath,
  relPathUnder,
  remoteDirname,
  remotePathBase,
  remotePathToUri,
  resolveRemoteWorkspacePath,
} from "./remote-paths.mjs";

test("listSshConfigHosts discovers concrete aliases, expands Include, skips wildcards and unsafe names", () => {
  const rootDir = path.resolve("virtual-ssh");
  const configFile = path.join(rootDir, "config");
  const confD = path.join(rootDir, "conf.d");
  const files = new Map([
    [path.resolve(configFile), [
      "Include conf.d/*.conf",
      "Host *",
      "  User defaultuser",
      "Host dev-box staging.internal",
      "  HostName 10.0.0.10",
      "  Port 2222",
      "Host *.example.com !excluded ?short -badflag unsafe;name",
      "  HostName 10.0.0.99",
      "Match host prod-*",
      "  User ignored",
    ].join("\n")],
    [path.resolve(path.join(confD, "a.conf")), [
      "Include ../config",
      "Host build-win",
      "  HostName 10.0.0.20",
      "  User builder",
      "  ProxyJump bastion",
    ].join("\n")],
    [path.resolve(path.join(confD, "b.conf")), [
      "Host dev-box",
      "  User second-ignored",
    ].join("\n")],
  ]);
  const io = {
    readFile: p => {
      const text = files.get(path.resolve(p));
      if (text === undefined) throw new Error("ENOENT");
      return text;
    },
    listDir: p => {
      if (path.resolve(p) === path.resolve(confD)) return ["b.conf", "a.conf", "readme.txt"];
      return [];
    },
    baseDir: rootDir,
  };

  const expanded = loadSshConfigText(configFile, io);
  assert.match(expanded, /Host build-win/);
  const hosts = listSshConfigHosts({ file: configFile, io });
  assert.deepEqual(hosts.map(h => h.alias), ["build-win", "dev-box", "staging.internal"]);

  const build = hosts.find(h => h.alias === "build-win");
  assert.equal(build.hostName, "10.0.0.20");
  assert.equal(build.user, "builder");
  assert.equal(build.proxyJump, "bastion");

  const dev = hosts.find(h => h.alias === "dev-box");
  assert.equal(dev.hostName, "10.0.0.10");
  assert.equal(dev.port, 2222);
  // First matching Host block wins for User (b.conf included before Host *).
  assert.equal(dev.user, "second-ignored");
});

test("parseHostBlocks handles line continuations, quoted tokens, equals syntax and negation", () => {
  const text = [
    "Host \"my-host\" \\",
    "  other-host",
    "  HostName=192.168.1.5",
    "  User = 'alice'",
    "Host * !my-host",
    "  Port 9999",
  ].join("\n");
  assert.deepEqual(splitValue(`"a b" 'c' d`), ["a b", "c", "d"]);
  assert.equal(parseHostBlocks(text).length, 2);
  const myHost = resolveSshHost("my-host", text);
  assert.equal(myHost.hostName, "192.168.1.5");
  assert.equal(myHost.user, "alice");
  assert.equal(myHost.port, 0);
  const other = resolveSshHost("other-host", text);
  assert.equal(other.port, 9999);
});

test("remote path helpers normalize POSIX, Windows drive, UNC and file URIs symmetrically", () => {
  assert.equal(isWindowsRemotePath("C:\\work"), true);
  assert.equal(isWindowsRemotePath("\\\\srv\\share"), true);
  assert.equal(isWindowsRemotePath("/home/dev"), false);

  assert.equal(normalizeRemotePath("/a/b/../c/", "linux"), "/a/c");
  assert.equal(normalizeRemotePath("", "linux"), "/");
  assert.equal(normalizeRemotePath("", "windows"), "");
  assert.equal(normalizeRemotePath("/c:/work/sub/../file.txt", "windows"), "C:\\work\\file.txt");
  assert.equal(normalizeRemotePath("d:/repo/", "windows"), "D:\\repo");
  assert.equal(normalizeRemotePath("\\\\srv\\share\\a\\..\\b", "windows"), "\\\\srv\\share\\b");

  assert.equal(joinRemotePath("/home/dev", "proj", "linux"), "/home/dev/proj");
  assert.equal(joinRemotePath("C:\\work", "proj", "windows"), "C:\\work\\proj");
  assert.equal(joinRemoteRel("C:\\work", "a/b/c.txt", "windows"), "C:\\work\\a\\b\\c.txt");

  assert.equal(remoteDirname("/home/dev/proj", "linux"), "/home/dev");
  assert.equal(remoteDirname("/", "linux"), "/");
  assert.equal(remoteDirname("C:\\work\\proj", "windows"), "C:\\work");
  assert.equal(remoteDirname("C:\\work", "windows"), "C:\\");
  assert.equal(remoteDirname("C:\\", "windows"), "");

  assert.equal(remotePathBase("/home/dev/proj/"), "proj");
  assert.equal(remotePathBase("C:\\"), "workspace");

  assert.equal(relPathUnder("C:\\Work\\App", "c:/work/app/src/index.ts"), "src/index.ts");
  assert.equal(relPathUnder("/home/dev/app", "/home/dev/other"), null);

  assert.equal(nativePathFromUri(remotePathToUri("/home/dev/a b.txt", "linux"), "linux"), "/home/dev/a b.txt");
  assert.equal(nativePathFromUri(remotePathToUri("C:\\Users\\dev\\my file.txt", "windows"), "windows"), "C:\\Users\\dev\\my file.txt");
  assert.equal(nativePathFromUri(remotePathToUri("\\\\srv\\share\\sub\\a.txt", "windows"), "windows"), "\\\\srv\\share\\sub\\a.txt");
});

test("resolveRemoteWorkspacePath maps relative, tilde, mirror, and cross-OS absolute paths", () => {
  const mirror = "C:\\Users\\local\\.umeko\\remote-workspaces\\dev\\repo-12345678";
  // Windows local client -> Linux remote
  assert.equal(
    resolveRemoteWorkspacePath("/home/dev/repo", "src/app.py", { mirrorDir: mirror, platform: "linux", homeDir: "/home/dev" }),
    "/home/dev/repo/src/app.py",
  );
  assert.equal(
    resolveRemoteWorkspacePath("/home/dev/repo", `${mirror}\\src\\app.py`, { mirrorDir: mirror, platform: "linux", homeDir: "/home/dev" }),
    "/home/dev/repo/src/app.py",
  );
  assert.equal(
    resolveRemoteWorkspacePath("/home/dev/repo", "~/notes.md", { mirrorDir: mirror, platform: "linux", homeDir: "/home/dev" }),
    "/home/dev/notes.md",
  );
  assert.equal(
    resolveRemoteWorkspacePath("/home/dev/repo", "@./README.md", { mirrorDir: mirror, platform: "linux", homeDir: "/home/dev" }),
    "/home/dev/repo/README.md",
  );

  // Windows remote
  assert.equal(
    resolveRemoteWorkspacePath("C:\\clients\\repo", "src/main.rs", { mirrorDir: mirror, platform: "windows", homeDir: "C:\\Users\\dev" }),
    "C:\\clients\\repo\\src\\main.rs",
  );
  assert.equal(
    resolveRemoteWorkspacePath("C:\\clients\\repo", "D:\\other\\x.txt", { mirrorDir: mirror, platform: "windows", homeDir: "C:\\Users\\dev" }),
    "D:\\other\\x.txt",
  );
  assert.throws(
    () => resolveRemoteWorkspacePath("C:\\clients\\repo", "C:relative.txt", { mirrorDir: mirror, platform: "windows" }),
    /Drive-relative/,
  );
});
