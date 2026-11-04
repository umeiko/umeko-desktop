"""Explicit platform requirements for full and Windows-first stable releases."""

ALL_PLATFORMS = frozenset(('windows-x64', 'macos-arm64', 'macos-x64', 'linux-x64'))
NATIVE_JOBS = {'windows-x64': 'Windows x64', 'macos-arm64': 'macOS Apple Silicon',
               'macos-x64': 'macOS Intel', 'linux-x64': 'Linux x64'}


def select_platforms(mode):
    if mode == 'all':
        return ALL_PLATFORMS
    if mode == 'windows':
        return frozenset(('windows-x64',))
    raise ValueError('Choose all or windows release platforms')


def asset_count(platforms):
    if not platforms or not set(platforms) <= ALL_PLATFORMS:
        raise ValueError('Invalid release platforms')
    # Archive, checksum and manifest per platform; DMG/checksum per Mac;
    # two SDK resources and the combined checksum file.
    return 3 * len(platforms) + 2 * sum(p.startswith('macos-') for p in platforms) + 3


def require_verified_jobs(jobs, platforms):
    if not platforms or not set(platforms) <= ALL_PLATFORMS:
        raise ValueError('Invalid release platforms')
    required = {'checks'} | {NATIVE_JOBS[p] for p in platforms}
    relevant = [j for j in jobs if j['name'] in required]
    successful = {j['name'] for j in relevant if j['conclusion'] == 'success'}
    if not required <= successful or any(j['conclusion'] != 'success' for j in relevant):
        raise ValueError('Shared checks and every selected native build must pass')
