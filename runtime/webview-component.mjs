// Conditional tool-result guidance only. Never injected into system prompts or UI.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

export const componentSpec = JSON.parse(await fs.readFile(new URL('./webview-component.json', import.meta.url), 'utf8'));
export const componentDirectory = () => process.env.UMEKO_WEBVIEW_COMPONENT_DIR || path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local/share'), 'umeko/components');
export async function webviewStatus(config = {}) {
  if (config.available) return {status:'ready'};
  if (process.platform !== 'linux') return {status:'unavailable', message:'当前构建未能加载系统 WebView，请检查应用安装。'};
  if (process.arch !== 'x64' || config.qt && config.qt !== componentSpec.qt) return {status:'unavailable',message:'此组件仅适用于 Qt '+componentSpec.qt+' 的 Linux x64 构建。'};
  if (config.error) return {status:'unavailable',message:'浏览器组件无法加载：'+config.error};
  const directory = config.directory || componentDirectory();
  try {
    const active = JSON.parse(await fs.readFile(path.join(directory, 'active.json'), 'utf8'));
    if (active.sha256 === componentSpec.sha256 && active.id === componentSpec.id && active.directory && active.directory === path.basename(active.directory)) {
      const root=path.join(directory, active.directory), manifest=JSON.parse(await fs.readFile(path.join(root,'manifest.json'),'utf8'));
      if (manifest.id !== componentSpec.id || manifest.qt !== componentSpec.qt) throw Error('Component mismatch');
      await Promise.all(['lib/libQt6WebEngineCore.so.6','libexec/QtWebEngineProcess','plugins/webview/libqtwebview_webengine.so'].map(file=>fs.access(path.join(root,file))));
      return {status:'restart_required', message:'Qt WebEngine 组件已安装，请告知用户在方便时重启 Umeko，然后重新提交网址；不要自动结束 Agent 任务。'};
    }
  } catch {}
  const folder = componentSpec.id + '-' + componentSpec.sha256.slice(0,16);
  return {
    status:'component_required', releaseUrl:componentSpec.releaseUrl, downloadUrl:componentSpec.url,
    filename:componentSpec.filename, bytes:componentSpec.bytes, sha256:componentSpec.sha256,
    installDirectory:path.join(directory, folder), activationFile:path.join(directory, 'active.json'),
    activation:{id:componentSpec.id,sha256:componentSpec.sha256,directory:folder},
    instructions:'This URL was delivered as a chat link, but the Linux side WebView needs an optional Qt WebEngine component. Tell the user why the pane did not open and provide the official release page and ZIP URL above. If GitHub access is blocked, the user can download using an accessible network or another device and give you the local ZIP path. You may use your existing tools to obtain the package. To install: verify the ZIP size and SHA-256 exactly against the values above before extracting; extract its contents into installDirectory, keeping lib/, libexec/, plugins/, qml/, resources/ and manifest.json directly inside that directory. Ensure libexec/QtWebEngineProcess has executable permission (chmod 755). Then atomically write the activation JSON above to activationFile. Do not modify system Qt or require sudo. Tell the user to restart Umeko when convenient, then resubmit the URL. Do not stop agents or restart the app automatically.'
  };
}
