"""Explicit platform requirements for full and Windows-first stable releases."""

ALL_PLATFORMS = frozenset(('windows-x64', 'macos-arm64', 'macos-x64', 'linux-x64'))


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
