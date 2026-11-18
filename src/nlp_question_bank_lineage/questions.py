"""题库版本、条件、答案依据和复核记录。

这里的数据模型刻意把「题干文本」和「可比较的结构化信息」分开保存：

* 题干的措辞可以变化；
* 条件有稳定的 ``condition_id``，限定值放在 ``value`` 中；
* 答案依据有稳定的 ``basis_id``，并通过 ``condition_ids`` 声明它依赖哪些条件；
* 复核记录绑定到具体的 ``question_id`` 和 ``revision``。

这样改编或修订时，系统比较的是条件和答案依据的引用关系，而不是题干文本的
相似度。无法从结构化信息判断影响时，分析结果会保持 ``indeterminate``，题
目也会保留在待审状态。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from .text import normalize_text


DECISIONS = ("approved", "rejected", "needs_changes", "inconclusive")

_DECISION_ALIASES = {
    "approve": "approved",
    "approved": "approved",
    "pass": "approved",
    "passed": "approved",
    "通过": "approved",
    "reject": "rejected",
    "rejected": "rejected",
    "fail": "rejected",
    "failed": "rejected",
    "驳回": "rejected",
    "needs_changes": "needs_changes",
    "needs_change": "needs_changes",
    "changes_requested": "needs_changes",
    "revise": "needs_changes",
    "需修改": "needs_changes",
    "inconclusive": "inconclusive",
    "uncertain": "inconclusive",
    "pending": "inconclusive",
    "needs_review": "inconclusive",
    "待定": "inconclusive",
}


def _clean(value):
    return "" if value is None else str(value).strip()


def _normalized(value):
    return normalize_text(_clean(value))


def _semantic_value(value):
    """把限定值变成可稳定比较的字符串。

    字符串按文本规范化处理；列表、字典等结构按排序后的 JSON 保存，以免键
    顺序造成虚假的「条件变化」。
    """

    if value is None:
        return None
    if isinstance(value, str):
        return normalize_text(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _string_tuple(value):
    if value is None:
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        raise ValueError("字段必须是字符串或字符串列表")
    result = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("condition_id", item.get("id", ""))
        text = _clean(item)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _parse_datetime(value, field="时间"):
    text = _clean(value)
    if not text:
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field}格式无效") from error
    return text


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def surface_key(text):
    """返回忽略大小写、空白和标点后的文本，用于识别纯格式调整。"""

    normalized = unicodedata.normalize("NFKC", _clean(text)).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )


@dataclass(frozen=True)
class Condition:
    condition_id: str
    text: str
    value: str | None = None
    kind: str = ""

    @classmethod
    def from_value(cls, value, index=0):
        if isinstance(value, str):
            value = {"text": value}
        if not isinstance(value, dict):
            raise ValueError("条件必须是对象或文本")
        condition_id = _clean(
            value.get("condition_id", value.get("id", value.get("key", "")))
        ) or f"condition-{index + 1}"
        raw_value = value.get("value")
        if raw_value is None:
            raw_value = value.get("constraint", value.get("semantic_value"))
        semantic = _semantic_value(raw_value)
        text = _normalized(value.get("text", value.get("label", value.get("description", ""))))
        if not text and semantic is not None:
            text = semantic
        if not text:
            raise ValueError(f"条件 {condition_id} 缺少描述或限定值")
        kind = _normalized(value.get("kind", value.get("type", value.get("category", ""))))
        return cls(condition_id=condition_id, text=text, value=semantic, kind=kind)

    def to_dict(self):
        return {
            "condition_id": self.condition_id,
            "text": self.text,
            "value": self.value,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class AnswerBasis:
    basis_id: str
    conclusion: str
    evidence: str = ""
    condition_ids: tuple[str, ...] = ()
    source_basis_id: str = ""

    @classmethod
    def from_value(cls, value, index=0):
        if isinstance(value, str):
            value = {"conclusion": value}
        if not isinstance(value, dict):
            raise ValueError("答案依据必须是对象或文本")
        basis_id = _clean(
            value.get("basis_id", value.get("id", value.get("answer_id", "")))
        ) or f"basis-{index + 1}"
        conclusion = _normalized(
            value.get("conclusion", value.get("answer", value.get("result", "")))
        )
        evidence = _normalized(
            value.get(
                "evidence",
                value.get(
                    "basis",
                    value.get("rationale", value.get("explanation", value.get("analysis", ""))),
                ),
            )
        )
        condition_ids = _string_tuple(
            value.get("condition_ids", value.get("depends_on", value.get("conditions", ())))
        )
        source_basis_id = _clean(
            value.get("source_basis_id", value.get("origin_basis_id", value.get("inherits", "")))
        )
        if not conclusion:
            raise ValueError(f"答案依据 {basis_id} 缺少结论")
        return cls(
            basis_id=basis_id,
            conclusion=conclusion,
            evidence=evidence,
            condition_ids=condition_ids,
            source_basis_id=source_basis_id,
        )

    def to_dict(self):
        return {
            "basis_id": self.basis_id,
            "conclusion": self.conclusion,
            "evidence": self.evidence,
            "condition_ids": list(self.condition_ids),
            "source_basis_id": self.source_basis_id,
        }


def _parse_derived_from(value):
    if value in (None, "", {}):
        return None
    if isinstance(value, str):
        text = value.strip()
        if "@" in text:
            question_id, revision = text.rsplit("@", 1)
        elif "#" in text:
            question_id, revision = text.rsplit("#", 1)
        else:
            question_id, revision = text, ""
        try:
            revision_value = int(revision) if revision.strip() else None
        except ValueError as error:
            raise ValueError("来源版本修订号无效") from error
        if not question_id.strip():
            raise ValueError("来源版本缺少题目编号")
        return {"question_id": question_id.strip(), "revision": revision_value}
    if not isinstance(value, dict):
        raise ValueError("来源版本必须由题目编号和修订号描述")
    question_id = _clean(
        value.get("question_id", value.get("source_question_id", value.get("id", "")))
    )
    raw_revision = value.get("revision", value.get("source_revision"))
    if raw_revision in (None, ""):
        revision = None
    else:
        try:
            revision = int(raw_revision)
        except (TypeError, ValueError) as error:
            raise ValueError("来源版本修订号无效") from error
        if revision < 1:
            raise ValueError("来源版本修订号无效")
    if not question_id:
        raise ValueError("来源版本缺少题目编号")
    return {"question_id": question_id, "revision": revision}

@dataclass(frozen=True)
class QuestionVersion:
    question_id: str
    revision: int
    source: str
    observed_at: str
    objective: str
    stem: str
    conditions: tuple[Condition, ...] = ()
    answer_bases: tuple[AnswerBasis, ...] = ()
    context: str = ""
    difficulty: str = ""
    tags: tuple[str, ...] = ()
    derived_from: dict | None = None

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("题目版本必须是对象")
        question_id = _clean(
            value.get("question_id", value.get("id", value.get("record_id", "")))
        )
        try:
            revision = int(value.get("revision", 0))
        except (TypeError, ValueError) as error:
            raise ValueError("题目版本修订号无效") from error
        source = _clean(value.get("source", ""))
        stem = _normalized(
            value.get("stem", value.get("text", value.get("question_stem", "")))
        )
        if not question_id or not source or revision < 1 or not stem:
            raise ValueError("题目版本缺少身份、来源、有效修订号或题干")
        raw_conditions = value.get("conditions", ())
        if raw_conditions is None:
            raw_conditions = ()
        if not isinstance(raw_conditions, (list, tuple)):
            raise ValueError("条件必须是列表")
        conditions = tuple(
            Condition.from_value(condition, index)
            for index, condition in enumerate(raw_conditions)
        )
        if len({condition.condition_id for condition in conditions}) != len(conditions):
            raise ValueError("同一版本中的条件编号不能重复")
        raw_bases = value.get(
            "answer_bases",
            value.get("answers", value.get("answer_basis", value.get("solutions", ()))),
        )
        if raw_bases is None:
            raw_bases = ()
        if not isinstance(raw_bases, (list, tuple)):
            raise ValueError("答案依据必须是列表")
        answer_bases = tuple(
            AnswerBasis.from_value(basis, index) for index, basis in enumerate(raw_bases)
        )
        if len({basis.basis_id for basis in answer_bases}) != len(answer_bases):
            raise ValueError("同一版本中的答案依据编号不能重复")
        return cls(
            question_id=question_id,
            revision=revision,
            source=source,
            observed_at=_parse_datetime(value.get("observed_at", ""), "观测时间"),
            objective=_normalized(
                value.get(
                    "objective",
                    value.get(
                        "curriculum_objective",
                        value.get("course_objective", value.get("goal", "")),
                    ),
                )
            ),
            stem=stem,
            conditions=conditions,
            answer_bases=answer_bases,
            context=_normalized(value.get("context", "")),
            difficulty=_normalized(value.get("difficulty", "")),
            tags=_string_tuple(value.get("tags", ())),
            derived_from=_parse_derived_from(value.get("derived_from")),
        )

    @property
    def key(self):
        return self.question_id, self.revision

    def to_dict(self):
        return {
            "question_id": self.question_id,
            "revision": self.revision,
            "source": self.source,
            "observed_at": self.observed_at,
            "objective": self.objective,
            "stem": self.stem,
            "conditions": [condition.to_dict() for condition in self.conditions],
            "answer_bases": [basis.to_dict() for basis in self.answer_bases],
            "context": self.context,
            "difficulty": self.difficulty,
            "tags": list(self.tags),
            "derived_from": dict(self.derived_from) if self.derived_from else None,
        }


# 便于调用方使用更贴近业务的名称。
QuestionRecord = QuestionVersion
Question = QuestionVersion


@dataclass(frozen=True)
class Review:
    question_id: str
    revision: int
    reviewer: str
    decision: str
    notes: str = ""
    reviewed_at: str = ""
    review_id: str = ""
    carry_forward: bool = True
    confirmed_basis_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("复核记录必须是对象")
        question_id = _clean(value.get("question_id", ""))
        try:
            revision = int(value.get("revision", 0))
        except (TypeError, ValueError) as error:
            raise ValueError("复核记录修订号无效") from error
        reviewer = _clean(value.get("reviewer", ""))
        raw_decision = _clean(value.get("decision", "")).lower()
        decision = _DECISION_ALIASES.get(raw_decision)
        if not question_id or revision < 1 or not reviewer or decision is None:
            raise ValueError("复核记录缺少题目、修订号、复核人或有效结论")
        reviewed_at = _parse_datetime(value.get("reviewed_at", ""), "复核时间")
        raw_carry = value.get("carry_forward", True)
        if isinstance(raw_carry, str):
            carry_forward = raw_carry.strip().lower() not in ("false", "0", "no")
        else:
            carry_forward = bool(raw_carry)
        return cls(
            question_id=question_id,
            revision=revision,
            reviewer=reviewer,
            decision=decision,
            notes=_normalized(value.get("notes", "")),
            reviewed_at=reviewed_at,
            review_id=_clean(value.get("review_id", "")),
            carry_forward=carry_forward,
            confirmed_basis_ids=_string_tuple(
                value.get("confirmed_basis_ids", value.get("confirmed_bases", ()))
            ),
        )

    def to_dict(self):
        return {
            "review_id": self.review_id,
            "question_id": self.question_id,
            "revision": self.revision,
            "reviewer": self.reviewer,
            "decision": self.decision,
            "notes": self.notes,
            "reviewed_at": self.reviewed_at,
            "carry_forward": self.carry_forward,
            "confirmed_basis_ids": list(self.confirmed_basis_ids),
        }
