"""Contract tests for RepoHunter's agent-facing evidence output (no network)."""
import unittest
from unittest.mock import patch

import repohunter_mcp as mcp


REPO = {
    "full_name": "example/project",
    "html_url": "https://github.com/example/project",
    "description": "A useful public project",
    "name": "project",
    "language": "Python",
    "topics": ["example"],
    "license": {"spdx_id": "MIT"},
    "stargazers_count": 42,
    "pushed_at": "2026-08-01T00:00:00Z",
    "created_at": "2024-01-01T00:00:00Z",
    "archived": False,
    "fork": False,
}


class EvidenceContract(unittest.TestCase):
    def assert_evidence(self, evidence, endpoint):
        self.assertEqual(evidence["schema"], "repohunter.evidence.v1")
        self.assertRegex(evidence["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(evidence["sources"][0]["endpoint"], "https://api.github.com" + endpoint)
        self.assertEqual(evidence["review"]["decision_owner"], "user")
        self.assertTrue(any("bias" in limit for limit in evidence["limits"]))
        self.assertTrue(any("not checked" in limit for limit in evidence["limits"]))

    @patch.object(mcp, "gh", return_value=REPO)
    def test_evaluate_repo_includes_reviewable_provenance(self, _gh):
        out = mcp.skill_evaluate_repo({"repo": "example/project", "project": "Python service"})
        self.assert_evidence(out["evidence"], "/repos/example/project")
        self.assertEqual(out["url"], REPO["html_url"])

    @patch.object(mcp, "gh", return_value={"items": [REPO]})
    def test_find_repos_records_search_route_and_limits(self, _gh):
        out = mcp.skill_find_repos({"query": "useful project"})
        self.assert_evidence(out["evidence"],
                             "/search/repositories?sort=stars&per_page=15&q=useful%20project")
        self.assertEqual(out["candidates"][0]["repo"], "example/project")

    @patch.object(mcp, "gh", return_value=[REPO])
    def test_public_work_summary_rejects_person_judgment(self, _gh):
        out = mcp.skill_portfolio_scan({"user": "example"})
        self.assert_evidence(out["evidence"],
                             "/users/example/repos?per_page=100&sort=updated&type=owner")
        self.assertIn("not an assessment of a person", out["_note"].lower())
        self.assertIn("does not imply", out["_note"].lower())


class UnidentifiedLicense(unittest.TestCase):
    def _repo(self, spdx):
        return {"stargazers_count": 250000, "pushed_at": "2099-01-01T00:00:00Z",
                "created_at": "2015-01-01T00:00:00Z", "archived": False,
                "license": {"spdx_id": spdx} if spdx is not None else None}

    def test_noassertion_or_missing_license_is_never_go(self):
        for spdx in ("NOASSERTION", None):
            self.assertEqual(mcp.score(self._repo(spdx))["verdict"], "MAYBE", spdx)

    def test_identified_license_can_be_go(self):
        self.assertEqual(mcp.score(self._repo("MIT"))["verdict"], "GO")


WIFI_REPO = dict(REPO, full_name="example/wifi-planner", name="wifi-planner",
                 description="Open-source Wi-Fi design: predictive heat maps and site surveys",
                 topics=["wifi", "wlan"])
SPAM_REPO = dict(REPO, full_name="example/sql-dump", name="sql-dump",
                 description="BEGIN TRANSACTION; CREATE TABLE Commands (Command_No INTEGER PRIMARY KEY)",
                 topics=[])


class FindReposQuality(unittest.TestCase):
    """Regression tests for the 2026-10-31 gate run: spam outranked relevant repos, the fallback
    dropped domain terms, relevance had a free base, and 'Wi-Fi' escaped the 'wifi' keyword."""

    @patch.object(mcp, "gh", return_value={"items": [SPAM_REPO, WIFI_REPO]})
    def test_zero_overlap_spam_is_filtered_out(self, _gh):
        out = mcp.skill_find_repos({"query": "wifi site survey design"})
        repos = [c["repo"] for c in out["candidates"]]
        self.assertEqual(repos, ["example/wifi-planner"])

    def test_fallback_prefers_domain_terms_over_long_generic_words(self):
        calls = []

        def fake_gh(endpoint):
            calls.append(endpoint)
            return {"items": []} if len(calls) == 1 else {"items": [WIFI_REPO]}

        with patch.object(mcp, "gh", side_effect=fake_gh):
            out = mcp.skill_find_repos({"query": "rf coverage prediction wifi"})
        self.assertEqual(out["fallback_query"], "rf wifi")
        self.assertTrue(calls[1].endswith("q=rf%20wifi"), calls[1])

    def test_relevance_has_no_free_base(self):
        s = mcp.score({"description": "database migration tooling", "topics": [],
                       "name": "dbtool", "stargazers_count": 10}, ["wifi", "wlan"])
        self.assertEqual(s["relevance"], 0)

    def test_wifi_keyword_matches_wi_fi_spelling(self):
        s = mcp.score({"description": "Wi-Fi site survey tool", "topics": [],
                       "name": "surveytool", "stargazers_count": 10}, ["wifi"])
        self.assertEqual(s["relevance"], 12)

    def test_short_acronym_does_not_match_inside_words(self):
        s = mcp.score({"description": "high performance computing", "topics": [],
                       "name": "hpc", "stargazers_count": 10}, ["rf"])
        self.assertEqual(s["relevance"], 0)

    def test_popular_spam_does_not_outrank_niche_match(self):
        low_star_relevant = dict(WIFI_REPO, full_name="example/niche", stargazers_count=1)
        high_star_spam = dict(REPO, full_name="example/popular", stargazers_count=9000,
                              description="totally unrelated commands dump", topics=[])
        with patch.object(mcp, "gh", return_value={"items": [high_star_spam, low_star_relevant]}):
            out = mcp.skill_find_repos({"query": "wifi survey"})
        self.assertEqual([c["repo"] for c in out["candidates"]], ["example/niche"])

    def test_kws_from_drops_generic_words_and_keeps_acronyms(self):
        kws = mcp._kws_from("RF wifi WLAN design tool for vendor-agnostic BOM plans")
        self.assertIn("rf", kws)
        self.assertIn("wifi", kws)
        self.assertIn("bom", kws)
        for junk in ("design", "tool", "plans", "plan"):
            self.assertNotIn(junk, kws)


if __name__ == "__main__":
    unittest.main()
