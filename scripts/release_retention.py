"""Retain minor-version milestones and only the newest patch in each series."""
import re

# Retain this user-designated milestone until its retention is explicitly lifted.
RETAINED_MILESTONES = frozenset(("v0.7.1",))


def latest_intel_release(releases):
    candidates = []
    for release in releases:
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", release["tag_name"])
        if match and not release["draft"] and not release.get("prerelease") and any(
            "-macos-x64-" in asset.get("name", "") and asset["name"].endswith(".dmg")
            for asset in release["assets"]
        ):
            candidates.append((tuple(map(int, match.groups())), release["tag_name"]))
    return max(candidates, default=((), None))[1]


def obsolete_patches(releases, tag):
    pattern = r"v(\d+)\.(\d+)\.(\d+)(?:-minimal)?"
    current = re.fullmatch(pattern, tag)
    if not current or int(current[3]) == 0: return []
    series = (current[1], current[2])
    # The owner retired 0.7.0 once a release newer than the 0.7.1 milestone exists.
    minimum_patch = 0 if series == ("0", "7") and int(current[3]) > 1 else 1
    result = []
    for release in releases:
        if release["tag_name"].removesuffix("-minimal") in RETAINED_MILESTONES:
            continue
        match = re.fullmatch(pattern, release["tag_name"])
        if match and not release["draft"] and (match[1], match[2]) == series and minimum_patch <= int(match[3]) < int(current[3]):
            result.append(release)
    return result


def prune_releases(repo, tag, api, gh):
    assert repo in ("umeiko/umeko-desktop", "umeiko/umeko-desktop-cpp")
    releases = api("releases?per_page=100")
    current = next(r for r in releases if r["tag_name"] == tag)
    assert not current["draft"]
    if repo.endswith("-cpp"):
        assert len(current["assets"]) in (15, 19)
        standard = tag.removesuffix("-minimal")
        pair = [next((r for r in releases if r["tag_name"] == name), None) for name in (standard, standard + "-minimal")]
        if any(not r or r["draft"] or len(r["assets"]) not in (15, 19) or r["target_commitish"] != current["target_commitish"] for r in pair):
            print("Old patch cleanup deferred until both native editions are published", flush=True)
            return []
    else:
        assert len(current["assets"]) in (14, 15, 19)
    retained_intel = latest_intel_release(releases) if not repo.endswith("-cpp") else None
    removed = []
    for release in obsolete_patches(releases, tag):
        if release["tag_name"] == retained_intel:
            continue
        gh("api", "--method", "DELETE", f"repos/{repo}/releases/{release['id']}")
        removed.append(release["tag_name"])
        print("Removed superseded patch Release and assets:", release["tag_name"], flush=True)
    return removed
