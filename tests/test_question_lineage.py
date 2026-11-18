import tempfile
import unittest
from pathlib import Path

from nlp_question_bank_lineage.lineage import compare_versions, find_duplicate_groups
from nlp_question_bank_lineage.question_workflow import QuestionWorkflow
from nlp_question_bank_lineage.repository import QuestionRepository


def question(**overrides):
    value = {
        "question_id": "q1",
        "revision": 1,
        "source": "synthetic",
        "observed_at": "2026-11-18T09:00:00Z",
        "objective": "分数比较",
        "stem": "比较 3/7 和 5/7 的大小。",
        "conditions": [
            {"condition_id": "denominator", "text": "同分母", "value": "same"},
        ],
        "answer_bases": [
            {
                "basis_id": "main",
                "conclusion": "3/7 < 5/7",
                "evidence": "同分母比分子。",
                "condition_ids": ["denominator"],
            }
        ],
    }
    value.update(overrides)
    return value


def review(**overrides):
    value = {
        "review_id": "r1",
        "question_id": "q1",
        "revision": 1,
        "reviewer": "教研员",
        "decision": "approved",
        "reviewed_at": "2026-11-18T09:05:00Z",
        "confirmed_basis_ids": ["main"],
    }
    value.update(overrides)
    return value


class QuestionLineageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.repository = QuestionRepository(
            Path(self.directory.name) / "questions.json"
        )
        self.workflow = QuestionWorkflow(self.repository)

    def tearDown(self):
        self.directory.cleanup()

    def assert_publishable(self, question_id, expected):
        view = self.workflow.trace(question_id)
        self.assertEqual(view["publishable"], expected, view["answer_bases"])
        return view

    def test_wording_only_revision_keeps_prior_approval(self):
        self.workflow.ingest(
            {
                "questions": [question()],
                "reviews": [review()],
            }
        )
        self.workflow.ingest(
            [
                question(
                    revision=2,
                    stem="请比较 3/7 与 5/7 的大小。",
                    conditions=[
                        {"condition_id": "denominator", "text": "分母一样", "value": "same"}
                    ],
                )
            ]
        )
        view = self.assert_publishable("q1", True)
        self.assertTrue(view["changes"]["wording_only"])
        self.assertEqual(view["answer_bases"][0]["status"], "confirmed")
        self.assertTrue(view["answer_bases"][0]["carried_forward"])
        self.assertEqual(view["needs_reconfirmation"], [])
        self.assertEqual(view["review"], None)
        self.assertEqual(view["carried_review"]["review_id"], "r1")

    def test_changed_condition_invalidates_answer_conclusion(self):
        self.workflow.ingest({"questions": [question()], "reviews": [review()]})
        self.workflow.ingest(
            [
                question(
                    revision=2,
                    stem="比较 3/7 和 5/9 的大小。",
                    conditions=[
                        {
                            "condition_id": "denominator",
                            "text": "分母不同",
                            "value": "different",
                        }
                    ],
                )
            ]
        )
        view = self.assert_publishable("q1", False)
        self.assertFalse(view["changes"]["wording_only"])
        self.assertEqual(view["answer_bases"][0]["status"], "stale")
        self.assertEqual(view["answer_bases"][0]["determinacy"], "determinate")
        self.assertEqual(view["stale_basis_ids"], ["main"])
        self.assertEqual(view["status"], "blocked")
        self.assertEqual(view["changes"]["answer_impact"], "definite")

    def test_selected_basis_can_be_reconfirmed_without_other_bases(self):
        first = question(
            answer_bases=[
                {
                    "basis_id": "main",
                    "conclusion": "3/7 < 5/7",
                    "evidence": "同分母比分子。",
                    "condition_ids": ["denominator"],
                },
                {
                    "basis_id": "note",
                    "conclusion": "需要注意分母是否相同",
                    "condition_ids": ["denominator"],
                },
            ]
        )
        self.workflow.ingest(
            {
                "questions": [first],
                "reviews": [review(confirmed_basis_ids=["main", "note"])],
            }
        )
        second = question(
            revision=2,
            conditions=[
                {"condition_id": "denominator", "text": "分母不同", "value": "different"}
            ],
            answer_bases=[
                {
                    "basis_id": "main",
                    "conclusion": "3/7 < 5/9",
                    "evidence": "通分后比较。",
                    "condition_ids": ["denominator"],
                },
                {
                    "basis_id": "note",
                    "conclusion": "需要注意分母是否相同",
                    "condition_ids": ["denominator"],
                },
            ],
        )
        self.workflow.ingest([second])
        self.workflow.ingest(
            {
                "reviews": [
                    review(
                        review_id="r2",
                        revision=2,
                        reviewed_at="2026-11-18T10:00:00Z",
                        confirmed_basis_ids=["main"],
                    )
                ]
            }
        )
        view = self.workflow.trace("q1")
        by_id = {basis["basis_id"]: basis for basis in view["answer_bases"]}
        self.assertEqual(by_id["main"]["status"], "confirmed")
        self.assertEqual(by_id["note"]["status"], "stale")
        self.assertEqual(view["stale_basis_ids"], ["note"])
        self.assertFalse(view["publishable"])

    def test_uncomparable_condition_change_stays_pending(self):
        self.workflow.ingest({"questions": [question()], "reviews": [review()]})
        self.workflow.ingest(
            [
                question(
                    revision=2,
                    conditions=[
                        {"condition_id": "denominator", "text": "分母相同或可以通分"}
                    ],
                )
            ]
        )
        view = self.workflow.trace("q1")
        self.assertEqual(view["answer_bases"][0]["status"], "needs_review")
        self.assertEqual(view["answer_bases"][0]["determinacy"], "indeterminate")
        self.assertEqual(view["indeterminate_basis_ids"], ["main"])
        self.assertEqual(view["status"], "pending_review")
        self.assertFalse(view["publishable"])

    def test_added_condition_without_declared_dependency_stays_pending(self):
        self.workflow.ingest({"questions": [question()], "reviews": [review()]})
        self.workflow.ingest(
            [
                question(
                    revision=2,
                    conditions=[
                        {"condition_id": "denominator", "text": "同分母", "value": "same"},
                        {"condition_id": "range", "text": "分数小于 1", "value": "0..1"},
                    ],
                )
            ]
        )
        view = self.workflow.trace("q1")
        self.assertEqual(view["answer_bases"][0]["status"], "needs_review")
        self.assertEqual(view["answer_bases"][0]["determinacy"], "indeterminate")
        self.assertFalse(view["publishable"])

    def test_missing_declared_source_is_not_publishable(self):
        self.workflow.ingest(
            [
                question(
                    derived_from={"question_id": "missing", "revision": 1}
                )
            ]
        )
        view = self.workflow.trace("q1")
        self.assertIn("source_issue", view["changes"])
        self.assertEqual(view["status"], "pending_review")
        self.assertFalse(view["publishable"])
        self.assertEqual(view["answer_bases"][0]["determinacy"], "indeterminate")

    def test_adaptation_links_to_source_and_invalidates_changed_condition(self):
        self.workflow.ingest({"questions": [question()], "reviews": [review()]})
        self.workflow.ingest(
            [
                question(
                    question_id="q1-hard",
                    revision=1,
                    derived_from={"question_id": "q1", "revision": 1},
                    conditions=[
                        {
                            "condition_id": "denominator",
                            "text": "分母不同",
                            "value": "different",
                        }
                    ],
                )
            ]
        )
        view = self.workflow.trace("q1-hard")
        self.assertEqual(
            view["source_version"], {"question_id": "q1", "revision": 1}
        )
        self.assertTrue(view["is_adaptation"])
        self.assertEqual(view["answer_bases"][0]["status"], "stale")
        self.assertFalse(view["publishable"])
        self.assertEqual(
            [row["question_id"] for row in self.workflow.pending_reconfirmations()],
            ["q1-hard"],
        )

    def test_same_stem_different_objectives_are_not_merged(self):
        self.workflow.ingest(
            [
                question(question_id="q-a", objective="分数比较"),
                question(question_id="q-b", objective="生活情境表达"),
                question(question_id="q-c", objective="分数比较"),
            ]
        )
        duplicates = self.workflow.duplicates()
        self.assertEqual(duplicates["auto_merged"], [])
        self.assertEqual(len(duplicates["same_stem_different_objectives"]), 1)
        cross = duplicates["same_stem_different_objectives"][0]
        self.assertFalse(cross["auto_merge"])
        self.assertEqual(
            [group["objective"] for group in cross["groups"]],
            ["分数比较", "生活情境表达"],
        )
        self.assertEqual(
            [row["question_ids"] for row in duplicates["groups"]],
            [["q-a", "q-c"]],
        )
        self.assertEqual(
            [row["question_id"] for row in self.workflow.list_questions()],
            ["q-a", "q-b", "q-c"],
        )

    def test_trace_exposes_versions_changes_and_pending_conclusions(self):
        self.workflow.ingest({"questions": [question()], "reviews": [review()]})
        self.workflow.ingest(
            [
                question(
                    revision=2,
                    conditions=[
                        {
                            "condition_id": "denominator",
                            "text": "分母不同",
                            "value": "different",
                        }
                    ],
                )
            ]
        )
        view = self.workflow.trace("q1", 2)
        self.assertEqual(view["source_version"], {"question_id": "q1", "revision": 1})
        self.assertEqual(
            [(row["revision"], row["is_current"]) for row in view["version_history"]],
            [(1, False), (2, True)],
        )
        self.assertEqual(view["version_history"][1]["parent"]["revision"], 1)
        self.assertEqual(view["needs_reconfirmation"], ["main"])
        self.assertEqual(
            [entry["condition_id"] for entry in view["changes"]["conditions"]["changed"]],
            ["denominator"],
        )
        first = self.workflow.trace("q1", 1)
        self.assertEqual(first["status"], "approved")
        self.assertTrue(first["publishable"])
        self.assertEqual(first["needs_reconfirmation"], [])

    def test_published_version_is_immutable(self):
        self.workflow.ingest([question()])
        with self.assertRaises(ValueError):
            self.workflow.ingest([question(stem="被静默覆盖的题干")])
        stored = self.repository.read()["versions"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["stem"], "比较 3/7 和 5/7 的大小。")

    def test_review_for_unknown_version_is_rejected_without_partial_write(self):
        with self.assertRaises(ValueError):
            self.workflow.ingest(
                {"questions": [question()], "reviews": [review(revision=9)]}
            )
        self.assertEqual(self.repository.read()["versions"], [])

    def test_basis_wording_change_keeps_condition_dependency_check(self):
        self.workflow.ingest({"questions": [question()], "reviews": [review()]})
        self.workflow.ingest(
            [
                question(
                    revision=2,
                    answer_bases=[
                        {
                            "basis_id": "main",
                            "conclusion": "3/7 < 5/7",
                            "evidence": "同分母比分子!",
                            "condition_ids": ["denominator"],
                        }
                    ],
                )
            ]
        )
        view = self.workflow.trace("q1")
        self.assertTrue(view["changes"]["wording_only"])
        self.assertEqual(view["changes"]["bases"]["changed"], [])
        self.assertEqual(view["answer_bases"][0]["status"], "confirmed")
        self.assertTrue(view["publishable"])

    def test_basis_semantic_change_requires_review_even_if_conditions_match(self):
        self.workflow.ingest({"questions": [question()], "reviews": [review()]})
        self.workflow.ingest(
            [
                question(
                    revision=2,
                    answer_bases=[
                        {
                            "basis_id": "main",
                            "conclusion": "3/7 > 5/7",
                            "evidence": "同分母比分子。",
                            "condition_ids": ["denominator"],
                        }
                    ],
                )
            ]
        )
        view = self.workflow.trace("q1")
        self.assertEqual(view["answer_bases"][0]["status"], "needs_review")
        self.assertFalse(view["publishable"])
        self.assertEqual(view["status"], "pending_review")

    def test_compare_versions_reports_structure_not_similarity(self):
        before = {
            "stem": "比较 3/7 和 5/7 的大小。",
            "objective": "分数比较",
            "conditions": [{"condition_id": "d", "text": "同分母", "value": "same"}],
            "answer_bases": [],
            "tags": [],
        }
        after = {
            **before,
            "stem": "请比较 3/7 与 5/7 的大小关系!",
            "conditions": [
                {"condition_id": "d", "text": "分母相同", "value": "same"}
            ],
        }
        changes = compare_versions(before, after)
        self.assertTrue(changes["wording_only"])
        self.assertEqual(changes["answer_impact"], "none")
        self.assertEqual(changes["conditions"]["changed"][0]["change"], "wording")

    def test_duplicate_groups_use_latest_revision(self):
        groups = find_duplicate_groups(
            [
                {**question(question_id="a"), "revision": 1, "stem": "旧题干"},
                {**question(question_id="a"), "revision": 2, "stem": "新题干"},
                {**question(question_id="b"), "revision": 1, "stem": "新题干"},
            ]
        )
        self.assertEqual(
            [row["question_ids"] for row in groups["groups"]], [["a", "b"]]
        )


if __name__ == "__main__":
    unittest.main()
