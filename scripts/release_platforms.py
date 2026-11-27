"""Platform requirements for stable releases."""

ALL_PLATFORMS = frozenset(('windows-x64', 'macos-arm64', 'macos-x64', 'linux-x64'))
NATIVE_JOBS = {'windows-x64': 'Windows x64', 'macos-arm64': 'macOS Apple Silicon',
               'macos-x64': 'macOS Intel', 'linux-x64': 'Linux x64'}


def select_platforms(mode, version):
    if mode == 'all':
        if int(version.rsplit('.', 1)[1]) == 0:
            return ALL_PLATFORMS
        return ALL_PLATFORMS - {'macos-x64'}
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
    for name in required:
        attempts = [job for job in jobs if job['name'] == name]
        latest = max((job.get('run_attempt', 1) for job in attempts), default=0)
        if not latest or any(job['conclusion'] != 'success' for job in attempts
                             if job.get('run_attempt', 1) == latest):
            raise ValueError(f'Required build job did not pass: {name}')
