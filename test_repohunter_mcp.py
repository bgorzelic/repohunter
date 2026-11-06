"""Contract tests for RepoHunter's agent-facing evidence output (no network)."""
import time
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

    @patch.object(mcp, "gh_text", return_value="")
    @patch.object(mcp, "gh", return_value=REPO)
    def test_evaluate_repo_includes_reviewable_provenance(self, _gh, _txt):
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


def _days_ago(n):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mcp.NOW - n * 86400))


# A mature, popular, fresh repo that scores GO on metadata alone.
GO_REPO = dict(REPO, full_name="example/popular", name="popular", stargazers_count=100000,
               pushed_at=_days_ago(2), created_at="2022-01-01T00:00:00Z")

# Wording taken from the real thedotmack/claude-mem v15.8.3 release notes (2026-11-02).
INCIDENT_NOTES = ("## Privacy fix\n\nBrowser setup no longer uploads your prompts without asking.\n\n"
                  "The browser setup scanned local agent histories and uploaded the full text of the last "
                  "30 days of prompts, with session IDs and folder paths, without asking.\n\n"
                  "Prompts already uploaded by earlier versions are not removed by this update.")


def routed(repo, releases=None, advisories=None, fail=()):
    """gh() stand-in that answers each API path differently."""
    def fake(path):
        for bad in fail:
            if bad in path:
                raise RuntimeError("boom")
        if "/releases" in path:
            return releases if releases is not None else []
        if "/security-advisories" in path:
            return advisories if advisories is not None else []
        return repo
    return fake


class VerdictSignals(unittest.TestCase):
    def evaluate(self, repo=GO_REPO, slug="example/popular", **kw):
        with patch.object(mcp, "gh", routed(repo, **kw)), patch.object(mcp, "gh_text", return_value=""):
            return mcp.skill_evaluate_repo({"repo": slug})

    def test_baseline_is_go(self):
        self.assertEqual(self.evaluate()["verdict"], "GO")

    def test_recent_release_with_consent_incident_caps_go_to_maybe(self):
        out = self.evaluate(releases=[{"tag_name": "v15.8.3", "name": "v15.8.3",
                                       "published_at": _days_ago(2), "body": INCIDENT_NOTES}])
        self.assertEqual(out["verdict"], "MAYBE")
        self.assertEqual(out["signals"]["flags"][0]["tag"], "v15.8.3")
        self.assertIn("without asking", out["signals"]["flags"][0]["excerpt"].lower())
        self.assertTrue(out["signals"]["verdict_capped"])
        self.assertLessEqual(len(out["signals"]["flags"][0]["excerpt"]), 200)

    def test_old_incident_release_is_not_flagged(self):
        out = self.evaluate(releases=[{"tag_name": "v1", "published_at": _days_ago(200), "body": INCIDENT_NOTES}])
        self.assertEqual(out["verdict"], "GO")
        self.assertEqual(out["signals"]["flags"], [])

    def test_ordinary_upload_wording_is_not_flagged(self):
        out = self.evaluate(releases=[{"tag_name": "v2", "published_at": _days_ago(1),
                                       "body": "Fix: uploaded files are retried. Security fix for the docs build."}])
        self.assertEqual(out["verdict"], "GO")

    def test_agent_permission_wording_is_not_a_privacy_incident(self):
        # Real release-note phrasing from Superpowers v7.0.1 and t3code v0.1.4: agents acting "without asking".
        for body in ("it skipped the doc without asking in 24 of 24 runs before this change",
                     "docs(agents): agents verify in a browser or simulator without asking"):
            out = self.evaluate(releases=[{"tag_name": "v9", "published_at": _days_ago(1), "body": body}])
            self.assertEqual(out["verdict"], "GO", body)
            self.assertEqual(out["signals"]["flags"], [], body)

    def test_data_egress_without_consent_is_flagged_in_either_order(self):
        for body in ("Telemetry is sent to our servers without consent.",
                     "Without your permission, the installer collected your shell history."):
            out = self.evaluate(releases=[{"tag_name": "v9", "published_at": _days_ago(1), "body": body}])
            self.assertEqual(out["verdict"], "MAYBE", body)

    def test_hostile_release_body_cannot_stall_the_scanner(self):
        # Regression for a ReDoS: unbounded \w* before a lazy gap made matching quadratic on a long
        # run of egress-like words. GitHub allows 125k-char release bodies; the scan must stay fast.
        for body in ("upload" * 20000, "sent " + "a" * 120000, "exfiltrat" + "e" * 120000):
            start = time.perf_counter()
            out = self.evaluate(releases=[{"tag_name": "v", "published_at": _days_ago(1), "body": body}])
            self.assertLess(time.perf_counter() - start, 2.0, body[:12])
            self.assertTrue(out["signals"]["release_notes_checked"])

    def test_oversize_release_notes_fail_closed_never_clean(self):
        # A hostile repo can pad notes past the scan cap so the incident wording is never read.
        # That must not look clean: report it, mark the scan partial, and never allow GO.
        body = "x " * 70000 + "Telemetry is sent to our servers without consent."
        out = self.evaluate(releases=[{"tag_name": "v", "published_at": _days_ago(1), "body": body}])
        self.assertEqual(out["verdict"], "MAYBE")
        self.assertEqual(out["signals"]["flags"][0]["kind"], "release-notes-truncated")
        self.assertTrue(out["signals"]["verdict_capped"])
        self.assertFalse(out["signals"]["release_notes_fully_checked"])

    def test_several_long_auto_generated_releases_are_fully_checked(self):
        # Regression: CopilotKit/OpenBot has three 40k-59k-char generated changelogs; they used to
        # trip the per-release cap and hold an otherwise-GO repo at MAYBE.
        rels = [{"tag_name": "v%d" % i, "published_at": _days_ago(i + 1), "body": "- fix thing\n" * n}
                for i, n in enumerate((4000, 4500, 5000))]
        self.assertGreater(len(rels[2]["body"]), 50000)
        out = self.evaluate(releases=rels)
        self.assertEqual(out["verdict"], "GO")
        self.assertTrue(out["signals"]["release_notes_fully_checked"])

    def test_total_scan_budget_fails_closed_across_many_releases(self):
        rels = [{"tag_name": "v%d" % i, "published_at": _days_ago(i + 1), "body": "y " * 60000}
                for i in range(8)]
        start = time.perf_counter()
        out = self.evaluate(releases=rels)
        self.assertLess(time.perf_counter() - start, 5.0)
        self.assertEqual(out["verdict"], "MAYBE")
        self.assertFalse(out["signals"]["release_notes_fully_checked"])

    def test_long_but_scannable_release_notes_are_fully_checked(self):
        body = "x " * 5000 + "Telemetry is sent to our servers without consent."
        out = self.evaluate(releases=[{"tag_name": "v", "published_at": _days_ago(1), "body": body}])
        self.assertEqual(out["signals"]["flags"][0]["kind"], "release-notes-privacy-or-security-incident")
        self.assertTrue(out["signals"]["release_notes_fully_checked"])

    def test_old_oversize_release_notes_do_not_matter(self):
        out = self.evaluate(releases=[{"tag_name": "v", "published_at": _days_ago(300), "body": "x" * 90000}])
        self.assertEqual(out["verdict"], "GO")
        self.assertTrue(out["signals"]["release_notes_fully_checked"])

    def test_cve_mention_is_informational_only(self):
        out = self.evaluate(releases=[{"tag_name": "v3", "published_at": _days_ago(1),
                                       "body": "Bump lodash to fix CVE-2026-12345."}])
        self.assertEqual(out["verdict"], "GO")
        self.assertEqual(out["signals"]["flags"][0]["kind"], "advisory-id-mentioned")

    def test_recent_published_advisory_caps_go(self):
        out = self.evaluate(advisories=[{"ghsa_id": "GHSA-abcd-1234-wxyz", "severity": "high",
                                         "summary": "Token leak", "published_at": _days_ago(30)}])
        self.assertEqual(out["verdict"], "MAYBE")
        self.assertEqual(out["signals"]["flags"][0]["kind"], "published-advisory")

    def test_signal_fetch_failure_degrades_and_says_so(self):
        out = self.evaluate(fail=("/releases", "/security-advisories"))
        self.assertEqual(out["verdict"], "GO")
        self.assertFalse(out["signals"]["release_notes_checked"])
        self.assertFalse(out["signals"]["advisories_checked"])

    def test_signals_never_raise_a_verdict(self):
        low = dict(GO_REPO, archived=True)
        self.assertEqual(self.evaluate(repo=low)["verdict"], "SKIP")

    def test_signal_endpoints_are_listed_in_evidence_after_the_repo_endpoint(self):
        out = self.evaluate()
        eps = [s["endpoint"] for s in out["evidence"]["sources"]]
        self.assertEqual(eps[0], "https://api.github.com/repos/example/popular")
        self.assertTrue(any("/releases" in e for e in eps))
        self.assertTrue(any("not checked" in l for l in out["evidence"]["limits"]))

    def test_rename_is_reported_and_endpoint_keeps_requested_name(self):
        moved = dict(GO_REPO, full_name="new-owner/ECC")
        out = self.evaluate(repo=moved, slug="old-owner/everything")
        self.assertEqual(out["resolved_name"], {"requested": "old-owner/everything", "resolved": "new-owner/ECC"})
        self.assertEqual(out["evidence"]["sources"][0]["endpoint"],
                         "https://api.github.com/repos/old-owner/everything")

    def test_case_only_difference_is_not_a_rename(self):
        out = self.evaluate(repo=dict(GO_REPO, full_name="Example/Popular"))
        self.assertNotIn("resolved_name", out)

    def test_fork_is_flagged_with_parent(self):
        out = self.evaluate(repo=dict(GO_REPO, fork=True, parent={"full_name": "upstream/popular"}))
        self.assertEqual(out["fork_of"], "upstream/popular")


class ReadmeRelevance(unittest.TestCase):
    META = {"description": "framework", "topics": [], "name": "fw", "stargazers_count": 10}

    def test_description_hits_still_score_twelve(self):
        s = mcp.score(dict(self.META, description="skills framework"), ["skills"])
        self.assertEqual(s["relevance"], 12)

    def test_readme_only_hit_scores_less_than_description_hit(self):
        s = mcp.score(self.META, ["skills"], readme="install the skills here")
        self.assertEqual(s["relevance"], 4)

    def test_readme_contribution_is_capped(self):
        kws = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
        s = mcp.score(self.META, kws, readme=" ".join(kws))
        self.assertEqual(s["relevance"], 24)

    def test_no_readme_means_no_change(self):
        self.assertEqual(mcp.score(self.META, ["skills"])["relevance"], 0)

    def test_asker_words_are_not_keywords(self):
        kws = mcp._kws_from("Claude Code user wanting skills, hooks and plugins; solo consulting")
        for junk in ("user", "wanting", "solo", "consulting"):
            self.assertNotIn(junk, kws)
        self.assertIn("skills", kws)


if __name__ == "__main__":
    unittest.main()
