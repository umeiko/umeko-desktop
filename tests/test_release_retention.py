import unittest
from scripts.release_retention import obsolete_patches, prune_releases


def release(tag, identifier=1, **changes):
    return dict(tag_name=tag, id=identifier, draft=False, assets=[{}]*15, target_commitish="fixture-commit", **changes)


class ReleaseRetentionTests(unittest.TestCase):
    def test_three_platform_patch_preserves_latest_stable_intel_download(self):
        older = release("v0.7.9", 9)
        intel = release("v0.7.10", 10)
        for row in (older, intel):
            row["assets"] = [{"name": f"Umeko-{row['tag_name'][1:]}-macos-x64-abcdef0.dmg"}]
        patch = {**release("v0.7.11", 11), "assets": [{}] * 14}
        current = {**release("v0.7.12", 12), "assets": [{}] * 14}
        rows = [older, intel, patch, current]
        calls = []
        self.assertEqual(prune_releases("umeiko/umeko-desktop", "v0.7.12",
                                       lambda _: rows, lambda *args: calls.append(args)), ["v0.7.9", "v0.7.11"])
        self.assertEqual([call[-1].rsplit("/", 1)[1] for call in calls], ["9", "11"])

    def test_retains_071_milestone_during_later_full_releases(self):
        rows = [release("v0.7.0", 1), release("v0.7.1", 2),
                release("v0.7.2", 3), release("v0.7.3", 4), release("v0.7.1-minimal", 5),
                release("v0.7.5", 6), {**release("v0.7.0", 7), "draft": True}]
        calls = []
        self.assertEqual([r["tag_name"] for r in obsolete_patches(rows, "v0.7.2")], ["v0.7.0"])
        self.assertEqual(prune_releases("umeiko/umeko-desktop", "v0.7.3",
                                       lambda _: rows, lambda *args: calls.append(args)), ["v0.7.0", "v0.7.2"])
        self.assertEqual(calls, [("api", "--method", "DELETE", "repos/umeiko/umeko-desktop/releases/1"),
                                 ("api", "--method", "DELETE", "repos/umeiko/umeko-desktop/releases/3")])

    def test_new_dmg_releases_have_nineteen_assets(self):
        old = release("v0.3.1", 2)
        current = release("v0.3.8", 3); current['assets'] = [{}] * 19
        minimal = release("v0.3.8-minimal", 4); minimal['assets'] = [{}] * 19
        rows = [old, current, minimal]; calls = []
        self.assertEqual(prune_releases("umeiko/umeko-desktop-cpp", "v0.3.8", lambda _: rows, lambda *args: calls.append(args)), ["v0.3.1"])
        self.assertEqual(len(calls), 1)

    def test_keeps_milestones_other_series_future_versions_and_drafts(self):
        tags = ["v0.2.9", "v0.3.0", "v0.3.1", "v0.3.3-minimal", "v0.3.4", "v0.3.4-minimal", "v0.3.5", "voices-v1"]
        rows = [release(tag, i) for i, tag in enumerate(tags)]
        draft = release("v0.3.2"); draft["draft"] = True; rows.append(draft)
        self.assertEqual([r["tag_name"] for r in obsolete_patches(rows, "v0.3.4")], ["v0.3.1", "v0.3.3-minimal"])
        self.assertEqual(obsolete_patches(rows, "v0.3.0"), [])

    def test_waits_for_both_native_editions_and_deletes_only_release_endpoints(self):
        rows = [release("v0.3.0"), release("v0.3.2", 2), release("v0.3.4-minimal", 4)]
        calls = []
        self.assertEqual(prune_releases("umeiko/umeko-desktop-cpp", "v0.3.4-minimal", lambda _: rows, lambda *args: calls.append(args)), [])
        self.assertEqual(calls, [])
        rows.append(release("v0.3.4", 5))
        self.assertEqual(prune_releases("umeiko/umeko-desktop-cpp", "v0.3.4", lambda _: rows, lambda *args: calls.append(args)), ["v0.3.2"])
        self.assertEqual(calls, [("api", "--method", "DELETE", "repos/umeiko/umeko-desktop-cpp/releases/2")])
