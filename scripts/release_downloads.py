"""Direct platform downloads shared by README and versioned release notes."""
import base64
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

REPOS = ('umeiko/umeko-desktop', 'umeiko/umeko-desktop-cpp')
PLATFORMS = (
    ('windows-x64', '.zip', 'windows.svg', 'Windows x64 ZIP'),
    ('macos-arm64', '.dmg', 'macos-arm64.svg', 'macOS Apple Silicon DMG'),
    ('macos-x64', '.dmg', 'macos-x64.svg', 'macOS Intel DMG'),
    ('linux-x64', '.tar.gz', 'linux.svg', 'Linux x64 TAR.GZ'),
)


def download_buttons(repo, tag, assets, section='release'):
    assert repo in REPOS and re.fullmatch(r'v\d+\.\d+\.\d+(?:-minimal)?', tag)
    assert section in ('standard', 'minimal', 'release')
    names = [a['name'] if isinstance(a, dict) else a for a in assets]
    prefix = ('UmekoCpp-' + tag if repo.endswith('-cpp') else 'Umeko-' + tag[1:]) + '-'
    links = []
    for platform, suffix, icon, label in PLATFORMS:
        candidates = [name for name in names if name.startswith(prefix + platform) and name.endswith(suffix)]
        if len(candidates) != 1:
            raise ValueError(f'Expected exactly one {platform} {suffix} download, found {len(candidates)}')
        url = f'https://github.com/{repo}/releases/download/{tag}/{quote(candidates[0], safe="")}'
        image = f'https://raw.githubusercontent.com/{repo}/main/docs/downloads/{icon}'
        links.append(f'[![{label}]({image})]({url})')
    edition = ' · Minimal / 精简版' if tag.endswith('-minimal') else ''
    return (f'<!-- umeko-downloads:{section}:start -->\n\n'
            f'**Download {tag}{edition} · 点击下载**\n\n' + '\n'.join(links) +
            f'\n\n<!-- umeko-downloads:{section}:end -->')


def replace_block(text, block, section):
    pattern = rf'<!-- umeko-downloads:{section}:start -->.*?<!-- umeko-downloads:{section}:end -->'
    if len(re.findall(pattern, text, flags=re.S)) != 1:
        raise ValueError(f'Expected one {section} download block')
    return re.sub(pattern, lambda _: block, text, flags=re.S)


def release_notes(text, repo, tag, assets):
    block = download_buttons(repo, tag, assets)
    if '<!-- umeko-downloads:release:start -->' in text:
        return replace_block(text, block, 'release')
    heading, separator, rest = text.partition('\n')
    return heading + '\n\n' + block + '\n' + (rest if separator else '')


def refresh_readmes(repo, tag, assets, api, gh):
    """Update only marked blocks on main after all release assets are verified."""
    section = 'minimal' if tag.endswith('-minimal') else 'standard'
    block = download_buttons(repo, tag, assets, section)
    paths = ('README.md',) if repo.endswith('-cpp') else ('README.md', 'README.zh-CN.md')
    for path in paths:
        for attempt in range(3):
            current = api('contents/' + path + '?ref=main')
            text = base64.b64decode(current['content']).decode('utf-8')
            updated = replace_block(text, block, section)
            if updated == text:
                break
            payload = Path('.release/readme-downloads.json')
            payload.parent.mkdir(parents=True, exist_ok=True)
            payload.write_text(json.dumps({
                'message': f'docs: refresh {tag} download buttons [skip ci]',
                'branch': 'main', 'sha': current['sha'],
                'content': base64.b64encode(updated.encode('utf-8')).decode('ascii'),
            }), encoding='utf-8')
            try:
                gh('api', '--method', 'PUT', f'repos/{repo}/contents/{path}', '--input', payload)
                print('Updated direct downloads:', path, tag, flush=True)
                break
            except subprocess.CalledProcessError:
                # Read the new content again rather than overwrite concurrent edits.
                if attempt == 2 or api('contents/' + path + '?ref=main')['sha'] == current['sha']:
                    raise
