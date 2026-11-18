"""题目版本、复核与溯源查询的工作流。"""

from __future__ import annotations

from .lineage import build_lineage, compare_versions, find_duplicate_groups
from .questions import QuestionVersion, Review, utc_now


class QuestionWorkflow:
    def __init__(self, repository):
        self.repository = repository

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def _store(self):
        value = self.repository.read()
        versions = [dict(row) for row in value.get("versions", [])]
        reviews = [dict(row) for row in value.get("reviews", [])]
        return versions, reviews

    @staticmethod
    def _group(versions):
        grouped = {}
        for version in versions:
            grouped.setdefault(version["question_id"], {})[
                version["revision"]
            ] = version
        return grouped

    @staticmethod
    def _reviews_for(reviews, question_id, revision):
        return [
            review
            for review in reviews
            if review.get("question_id") == question_id
            and review.get("revision") == revision
        ]

    def _parent(self, grouped, version):
        """确定直接来源版本，并返回 (parent, ancestors, issue)。"""

        declared = version.get("derived_from")
        if declared:
            if (
                declared["question_id"] == version["question_id"]
                and declared.get("revision") == version["revision"]
            ):
                return None, [], "来源版本不能指向自身"
            parent_group = grouped.get(declared["question_id"])
            if not parent_group:
                return (
                    None,
                    [],
                    f"声明的来源题目 {declared['question_id']} 不在题目库中",
                )
            revision = declared.get("revision")
            if revision is None:
                revision = max(parent_group)
            parent = parent_group.get(revision)
            if parent is None:
                return (
                    None,
                    [],
                    f"声明的来源版本 {declared['question_id']}@{revision} 不在题目库中",
                )
            ancestors = []
            seen = {(parent["question_id"], parent["revision"])}
            cursor = parent
            while cursor and cursor.get("derived_from"):
                source = cursor["derived_from"]
                source_group = grouped.get(source["question_id"], {})
                source_revision = source.get("revision")
                if source_revision is None and source_group:
                    source_revision = max(source_group)
                candidate = source_group.get(source_revision) if source_revision else None
                if candidate is None:
                    break
                key = (candidate["question_id"], candidate["revision"])
                if key in seen:
                    break
                seen.add(key)
                ancestors.append(
                    {
                        "question_id": candidate["question_id"],
                        "revision": candidate["revision"],
                    }
                )
                cursor = candidate
            return parent, list(reversed(ancestors)), None

        same_group = grouped.get(version["question_id"], {})
        candidates = [
            record for revision, record in same_group.items() if revision < version["revision"]
        ]
        if not candidates:
            return None, [], None
        parent = max(candidates, key=lambda row: row["revision"])
        ancestors = [
            {"question_id": row["question_id"], "revision": row["revision"]}
            for row in sorted(candidates, key=lambda row: row["revision"], reverse=True)
        ]
        return parent, ancestors, None

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def ingest(self, values):
        """导入题目版本和/或复核记录。

        支持三种输入：版本列表、``{"questions": [...], "reviews": [...]}``，
        或 ``records.json`` 风格的 ``{"records": [...]}``（按题目版本解析）。
        """

        if isinstance(values, dict):
            if "reviews" in values or "questions" in values or "versions" in values:
                raw_questions = values.get(
                    "questions", values.get("versions", [])
                )
                raw_reviews = values.get("reviews", [])
            elif "records" in values:
                raw_questions = values.get("records", [])
                raw_reviews = []
            else:
                raise ValueError("导入对象需要包含 questions/versions 或 reviews")
        elif isinstance(values, list):
            raw_questions = values
            raw_reviews = []
        else:
            raise TypeError("导入内容必须是记录列表或包含 questions/reviews 的对象")
        if not isinstance(raw_questions, list) or not isinstance(raw_reviews, list):
            raise ValueError("questions 和 reviews 必须是列表")

        incoming_questions = [
            QuestionVersion.from_dict(value) for value in raw_questions
        ]
        incoming_reviews = [Review.from_dict(value) for value in raw_reviews]

        versions, reviews = self._store()
        known_versions = {
            (row["question_id"], row["revision"]): row for row in versions
        }
        known_reviews = {
            (row["question_id"], row["revision"], row["review_id"]): row
            for row in reviews
        }

        stored = 0
        skipped = 0
        for question in incoming_questions:
            key = question.key
            previous = known_versions.get(key)
            if previous is not None and previous != question.to_dict():
                raise ValueError(
                    f"题目版本 {question.question_id}@{question.revision} 已存在且内容不同，"
                    "版本不可覆盖，请使用新的修订号"
                )
            if previous is None:
                known_versions[key] = question.to_dict()
                stored += 1
            else:
                skipped += 1

        accepted_reviews = 0
        for review in incoming_reviews:
            key = (review.question_id, review.revision)
            if key not in known_versions:
                raise ValueError(
                    f"复核记录引用了不存在的版本 {review.question_id}@{review.revision}"
                )
            known_basis_ids = {
                basis["basis_id"]
                for basis in known_versions[key].get("answer_bases", ())
            }
            unknown_basis_ids = sorted(
                set(review.confirmed_basis_ids) - known_basis_ids
            )
            if unknown_basis_ids:
                raise ValueError(
                    "复核记录确认了不存在的答案依据："
                    + "、".join(unknown_basis_ids)
                )
            review_id = review.review_id
            if not review_id:
                base = "review-{}-{}".format(review.question_id, review.revision)
                existing_ids = {
                    existing_id
                    for (existing_question, existing_revision, existing_id) in known_reviews
                    if (existing_question, existing_revision) == key
                }
                suffix = 1
                review_id = base
                while review_id in existing_ids:
                    suffix += 1
                    review_id = f"{base}-{suffix}"
                review = Review(
                    **{
                        **review.__dict__,
                        "review_id": review_id,
                        "reviewed_at": review.reviewed_at or utc_now(),
                    }
                )
            review_key = (review.question_id, review.revision, review.review_id)
            payload = review.to_dict()
            if review_key in known_reviews and known_reviews[review_key] != payload:
                raise ValueError(
                    f"复核记录 {review.review_id} 已存在且内容不同，请使用新的复核编号"
                )
            if review_key not in known_reviews:
                known_reviews[review_key] = payload
                accepted_reviews += 1

        self.repository.replace(list(known_versions.values()), list(known_reviews.values()))
        return {
            "received": len(incoming_questions) + len(incoming_reviews),
            "stored_versions": stored,
            "skipped_versions": skipped,
            "stored_reviews": accepted_reviews,
            "total_versions": len(known_versions),
            "total_reviews": len(known_reviews),
        }

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _lineage_for(self, versions, reviews, version):
        grouped = self._group(versions)
        parent, ancestors, issue = self._parent(grouped, version)
        changes = compare_versions(parent, version)
        if issue:
            changes["summary"].append(issue)
            changes["source_issue"] = issue
        return build_lineage(
            version,
            parent,
            changes,
            self._reviews_for(reviews, version["question_id"], version["revision"]),
            self._reviews_for(
                reviews,
                parent["question_id"],
                parent["revision"],
            )
            if parent
            else [],
            ancestors,
        )

    def list_questions(self, question_id=None, status=None):
        versions, reviews = self._store()
        grouped = self._group(versions)
        if question_id:
            selected = [
                version
                for revision, version in sorted(grouped.get(question_id, {}).items())
            ]
        else:
            selected = [
                version
                for version in versions
                if grouped[version["question_id"]]
                and version["revision"] == max(grouped[version["question_id"]])
            ]
        result = [
            self._lineage_for(versions, reviews, version) for version in selected
        ]
        if status:
            result = [row for row in result if row["status"] == status]
        return sorted(result, key=lambda row: (row["question_id"], row["revision"]))

    def list_versions(self, question_id):
        versions, reviews = self._store()
        grouped = self._group(versions)
        if question_id not in grouped:
            raise KeyError(f"题目 {question_id} 不在题目库中")
        return [
            self._lineage_for(versions, reviews, version)
            for _, version in sorted(grouped[question_id].items())
        ]

    def trace(self, question_id, revision=None):
        """返回一题的完整溯源视图：来源链、修改点和待重新确认的结论。

        ``revision`` 省略时查看最新修订；查看旧修订不会改变它的历史状态。
        """

        versions, reviews = self._store()
        grouped = self._group(versions)
        if question_id not in grouped:
            raise KeyError(f"题目 {question_id} 不在题目库中")
        if revision is None:
            revision = max(grouped[question_id])
        version = grouped[question_id].get(revision)
        if version is None:
            raise KeyError(f"题目 {question_id} 没有修订 {revision}")
        view = self._lineage_for(versions, reviews, version)

        versions_by_revision = []
        for other_revision, other in sorted(grouped[question_id].items()):
            parent, _, issue = self._parent(grouped, other)
            changes = compare_versions(parent, other)
            versions_by_revision.append(
                {
                    "revision": other_revision,
                    "observed_at": other.get("observed_at", ""),
                    "is_current": other_revision == revision,
                    "parent": (
                        {
                            "question_id": parent["question_id"],
                            "revision": parent["revision"],
                        }
                        if parent
                        else None
                    ),
                    "source_issue": issue,
                    "changes": changes,
                    "review": (
                        sorted(
                            self._reviews_for(reviews, question_id, other_revision),
                            key=lambda row: row.get("reviewed_at", ""),
                        )[-1]
                        if self._reviews_for(reviews, question_id, other_revision)
                        else None
                    ),
                }
            )
        view["version_history"] = versions_by_revision
        view["reviews"] = sorted(
            self._reviews_for(reviews, question_id, revision),
            key=lambda row: row.get("reviewed_at", ""),
        )
        view["publishable"] = view["publishable"] and not view.get("source_issue")
        view["status"] = (
            "pending_review" if view.get("source_issue") else view["status"]
        )
        if view.get("source_issue"):
            view["publishable"] = False
        return view

    def pending_reconfirmations(self, question_id=None):
        versions, reviews = self._store()
        grouped = self._group(versions)
        rows = []
        for version in versions:
            if question_id and version["question_id"] != question_id:
                continue
            if version["revision"] != max(grouped[version["question_id"]]):
                continue
            view = self._lineage_for(versions, reviews, version)
            if not view["needs_reconfirmation"] and not view.get("source_issue"):
                continue
            rows.append(
                {
                    "question_id": view["question_id"],
                    "revision": view["revision"],
                    "status": view["status"],
                    "source_version": view["source_version"],
                    "needs_reconfirmation": view["needs_reconfirmation"],
                    "stale_basis_ids": view["stale_basis_ids"],
                    "indeterminate_basis_ids": view["indeterminate_basis_ids"],
                    "reasons": {
                        item["basis_id"]: item["reason"]
                        for item in view["answer_bases"]
                        if item["status"] != "confirmed"
                    },
                }
            )
        return sorted(rows, key=lambda row: (row["question_id"], row["revision"]))

    def duplicates(self):
        versions, _ = self._store()
        return find_duplicate_groups(versions)

    def list_reviews(self, question_id=None):
        _, reviews = self._store()
        if question_id:
            reviews = [
                review
                for review in reviews
                if review.get("question_id") == question_id
            ]
        return sorted(
            reviews,
            key=lambda row: (
                row.get("question_id", ""),
                row.get("revision", 0),
                row.get("reviewed_at", ""),
            ),
        )
