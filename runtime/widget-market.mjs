// Public Widget-market GET bridge. Share updater networking, never its installer.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {updateRequest} from './update-engine.mjs';

const repository = 'umeiko/umeko-desktop-widgets';
export function officialURL(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.port || url.username || url.password || url.hash) throw Error('Widget 市场地址无效');
  const valid = url.hostname === 'api.github.com' && url.pathname === `/repos/${repository}/releases` &&
    [...url.searchParams.keys()].every(key => ['per_page','page'].includes(key)) && url.searchParams.get('per_page') === '100' && /^[1-9][0-9]*$/.test(url.searchParams.get('page') || '') ||
    url.hostname === 'raw.githubusercontent.com' && !url.search && new RegExp(`^/${repository}/[^/]+/widgets/[a-z0-9][a-z0-9-]{0,63}/manifest\\.json$`).test(url.pathname) ||
    url.hostname === 'github.com' && !url.search && new RegExp(`^/${repository}/releases/download/[^/]+/[^/]+\\.zip$`).test(url.pathname);
  if (!valid) throw Error('只允许从官方 Widget 仓库获取内容');
  return url.href;
}

export async function marketRequest(job, fetcher = updateRequest) {
  const url = officialURL(job.url);
  const headers = {'User-Agent':'Umeko-Widget-Market','Accept':'application/vnd.github+json'};
  if (typeof job.headers?.['If-None-Match'] === 'string') headers['If-None-Match'] = job.headers['If-None-Match'];
  const response = await fetcher(url, {headers});
  const status = response.statusCode;
  const result = {status, headers:response.headers || {}};
  if (job.destination && status === 200) {
    const file = await fs.open(job.destination, 'wx', 0o600);
    try {
      let size = 0;
      for await (const chunk of response) {
        size += chunk.length;
        if (size > 128 * 1024 * 1024) throw Error('Widget 下载包超过 128 MiB');
        await file.write(chunk);
      }
    } catch (error) {
      response.destroy?.();
      throw error;
    } finally { await file.close(); }
  } else {
    const chunks = []; let size = 0;
    const limit = url.includes('raw.githubusercontent.com') ? 65536 : 4 * 1024 * 1024;
    for await (const chunk of response) {
      size += chunk.length;
      if (size > limit) { response.destroy?.(); throw Error('Widget 市场信息过大'); }
      chunks.push(Buffer.from(chunk));
    }
    result.body = Buffer.concat(chunks).toString('utf8');
  }
  return result;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    let input = '';
    for await (const chunk of process.stdin) { input += chunk; if (input.length > 16384) throw Error('Widget 请求无效'); }
    process.stdout.write(JSON.stringify(await marketRequest(JSON.parse(input))));
  } catch (error) {
    process.stdout.write(JSON.stringify({error:error.message || 'Widget 网络请求失败'}));
    process.exitCode = 1;
  }
}
