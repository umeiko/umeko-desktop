import unittest
from scripts.release_retention import obsolete_patches, prune_releases


def release(tag, identifier=1, **changes):
    return dict(tag_name=tag, id=identifier, draft=False, assets=[{}]*15, target_commitish="fixture-commit", **changes)


class ReleaseRetentionTests(unittest.TestCase):
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
