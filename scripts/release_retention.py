"""Retain minor-version milestones and only the newest patch in each series."""
import re


def obsolete_patches(releases, tag):
    pattern = r"v(\d+)\.(\d+)\.(\d+)(?:-minimal)?"
    current = re.fullmatch(pattern, tag)
    if not current or int(current[3]) == 0: return []
    series = (current[1], current[2])
    result = []
    for release in releases:
        match = re.fullmatch(pattern, release["tag_name"])
        if match and not release["draft"] and (match[1], match[2]) == series and 0 < int(match[3]) < int(current[3]):
            result.append(release)
    return result


def prune_releases(repo, tag, api, gh):
    assert repo in ("umeiko/umeko-desktop", "umeiko/umeko-desktop-cpp")
    releases = api("releases?per_page=100")
    current = next(r for r in releases if r["tag_name"] == tag)
    assert not current["draft"] and len(current["assets"]) == 15
    if repo.endswith("-cpp"):
        standard = tag.removesuffix("-minimal")
        pair = [next((r for r in releases if r["tag_name"] == name), None) for name in (standard, standard + "-minimal")]
        if any(not r or r["draft"] or len(r["assets"]) != 15 or r["target_commitish"] != current["target_commitish"] for r in pair):
            print("Old patch cleanup deferred until both native editions are published", flush=True)
            return []
    removed = []
    for release in obsolete_patches(releases, tag):
        gh("api", "--method", "DELETE", f"repos/{repo}/releases/{release['id']}")
        removed.append(release["tag_name"])
        print("Removed superseded patch Release and assets:", release["tag_name"], flush=True)
    return removed
