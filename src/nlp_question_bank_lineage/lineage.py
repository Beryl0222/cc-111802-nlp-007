"""版本溯源与可发布性判定。

判定不依赖题干相似度，而依赖显式记录的结构：

* ``condition_id`` 标识限定条件，``value`` 保存可比较的限定值；
* ``answer_basis.condition_ids`` 声明该结论依赖哪些条件；
* ``derived_from`` 声明改编题来自哪个题目的哪个修订；
* 同一 ``question_id`` 的修订按修订号形成版本链。

由此可以区分三类变化：

1. 仅题干措辞、标签等变化：条件语义未变，原答案依据继续成立；
2. 条件被新增、删除或限定值改变：声明依赖它的答案依据必须重新确认；
3. 缺少依赖声明、引用了不存在的条件或来源版本不可解析：无法判定，保持待审。
"""

from __future__ import annotations

from typing import Iterable

from .questions import surface_key


CONFIRMED = "confirmed"
RETAINED = "retained"
NEEDS_REVIEW = "needs_review"
STALE = "stale"

DETERMINATE = "determinate"
INDETERMINATE = "indeterminate"

_WORDING = "wording"
_SEMANTIC = "semantic"
_UNKNOWN = "unknown"


def _index(items, key):
    return {item[key]: item for item in items}


def _condition_change_status(previous, current):
    """比较同一编号的条件，返回 (change_kind, reason)。

    ``value`` 是可比较的限定值。只要两版都给出该值，就能把「值相同、表述不
    同」判为措辞变化；缺少限定值时，文本变化无法证明语义等价，归为未知。
    """

    if previous == current:
        return None, ""
    if previous.get("value") is not None and current.get("value") is not None:
        if previous["value"] == current["value"]:
            return _WORDING, "限定值未变，仅条件表述调整"
        return _SEMANTIC, "限定值发生变化"
    if previous.get("value") is None and current.get("value") is None:
        return _UNKNOWN, "条件缺少可比较的限定值，文本变化无法判定是否等价"
    return _UNKNOWN, "条件限定值信息不完整，无法比较"


def compare_versions(previous, current):
    """比较两个题目版本，返回结构化修改点。

    ``previous`` 可以为 ``None``，表示没有可比对的来源版本。
    """

    current = dict(current)
    changes = {
        "has_source": previous is not None,
        "stem": {
            "changed": False,
            "formatting_only": False,
            "before": previous.get("stem", "") if previous else "",
            "after": current.get("stem", ""),
        },
        "objective": {
            "changed": False,
            "before": previous.get("objective", "") if previous else "",
            "after": current.get("objective", ""),
        },
        "difficulty": {
            "changed": False,
            "before": previous.get("difficulty", "") if previous else "",
            "after": current.get("difficulty", ""),
        },
        "tags": {
            "changed": False,
            "added": [],
            "removed": [],
        },
        "conditions": {
            "added": [],
            "removed": [],
            "changed": [],
            "unchanged": [],
        },
        "bases": {
            "added": [],
            "removed": [],
            "changed": [],
            "unchanged": [],
            "wording": [],
        },
        "wording_only": False,
        "answer_impact": "none",
        "summary": [],
    }
    if previous is None:
        changes["wording_only"] = False
        changes["answer_impact"] = "not_comparable"
        changes["summary"].append("没有可比的来源版本")
        return changes

    previous = dict(previous)

    if previous.get("stem", "") != current.get("stem", ""):
        changes["stem"]["changed"] = True
        changes["stem"]["formatting_only"] = (
            surface_key(previous.get("stem", "")) == surface_key(current.get("stem", ""))
        )
        if changes["stem"]["formatting_only"]:
            changes["summary"].append("题干仅有标点、空白或大小写变化")
        else:
            changes["summary"].append("题干表述发生变化")

    if previous.get("objective", "") != current.get("objective", ""):
        changes["objective"]["changed"] = True
        changes["summary"].append("课程目标发生变化")

    if previous.get("difficulty", "") != current.get("difficulty", ""):
        changes["difficulty"]["changed"] = True
        changes["summary"].append("难度标记发生变化")

    previous_tags = list(previous.get("tags", ()))
    current_tags = list(current.get("tags", ()))
    added_tags = [tag for tag in current_tags if tag not in previous_tags]
    removed_tags = [tag for tag in previous_tags if tag not in current_tags]
    if added_tags or removed_tags:
        changes["tags"]["changed"] = True
        changes["tags"]["added"] = added_tags
        changes["tags"]["removed"] = removed_tags
        changes["summary"].append("标签发生变化")

    previous_conditions = _index(previous.get("conditions", ()), "condition_id")
    current_conditions = _index(current.get("conditions", ()), "condition_id")
    semantic_ids = []
    unknown_ids = []
    added_condition_ids = []
    removed_condition_ids = []
    for condition_id in current_conditions:
        if condition_id not in previous_conditions:
            added_condition_ids.append(condition_id)
            changes["conditions"]["added"].append(dict(current_conditions[condition_id]))
    for condition_id in previous_conditions:
        if condition_id not in current_conditions:
            removed_condition_ids.append(condition_id)
            changes["conditions"]["removed"].append(dict(previous_conditions[condition_id]))
    for condition_id, before in previous_conditions.items():
        after = current_conditions.get(condition_id)
        if after is None:
            continue
        kind, reason = _condition_change_status(before, after)
        if kind is None:
            changes["conditions"]["unchanged"].append(condition_id)
        elif kind == _WORDING:
            changes["conditions"]["unchanged"].append(condition_id)
            changes["conditions"]["changed"].append(
                {
                    "condition_id": condition_id,
                    "change": _WORDING,
                    "reason": reason,
                    "before": dict(before),
                    "after": dict(after),
                }
            )
        else:
            if kind == _SEMANTIC:
                semantic_ids.append(condition_id)
            else:
                unknown_ids.append(condition_id)
            changes["conditions"]["changed"].append(
                {
                    "condition_id": condition_id,
                    "change": kind,
                    "reason": reason,
                    "before": dict(before),
                    "after": dict(after),
                }
            )
    if added_condition_ids:
        changes["summary"].append("新增限定条件：" + "、".join(added_condition_ids))
    if removed_condition_ids:
        changes["summary"].append("删除限定条件：" + "、".join(removed_condition_ids))
    if semantic_ids:
        changes["summary"].append("限定值变化：" + "、".join(semantic_ids))
    if unknown_ids:
        changes["summary"].append("条件变化无法判定：" + "、".join(unknown_ids))

    previous_bases = _index(previous.get("answer_bases", ()), "basis_id")
    current_bases = _index(current.get("answer_bases", ()), "basis_id")
    for basis_id, basis in current_bases.items():
        match = previous_bases.get(basis_id)
        if match is None and basis.get("source_basis_id"):
            match = previous_bases.get(basis["source_basis_id"])
        if match is None:
            changes["bases"]["added"].append(basis_id)
            continue
        before = _basis_signature(match)
        after = _basis_signature(basis)
        if before == after:
            changes["bases"]["unchanged"].append(basis_id)
        elif _basis_wording_only(match, basis):
            changes["bases"]["unchanged"].append(basis_id)
            changes["bases"]["wording"].append(
                {
                    "basis_id": basis_id,
                    "matched_basis_id": match["basis_id"],
                    "reason": "结论与依据仅措辞或标点变化",
                }
            )
        else:
            changes["bases"]["changed"].append(
                {
                    "basis_id": basis_id,
                    "matched_basis_id": match["basis_id"],
                    "before": dict(match),
                    "after": dict(basis),
                }
            )
    matched_ids = {
        entry["matched_basis_id"] for entry in changes["bases"]["changed"]
    }
    matched_ids.update(changes["bases"]["unchanged"])
    for basis_id in previous_bases:
        if basis_id not in matched_ids and basis_id not in current_bases:
            changes["bases"]["removed"].append(basis_id)
    if changes["bases"]["added"]:
        changes["summary"].append("新增答案依据：" + "、".join(changes["bases"]["added"]))
    if changes["bases"]["removed"]:
        changes["summary"].append("删除答案依据：" + "、".join(changes["bases"]["removed"]))
    if changes["bases"]["changed"]:
        changes["summary"].append(
            "修改答案依据：" + "、".join(entry["basis_id"] for entry in changes["bases"]["changed"])
        )

    structural = (
        changes["objective"]["changed"]
        or added_condition_ids
        or removed_condition_ids
        or semantic_ids
        or unknown_ids
        or changes["bases"]["added"]
        or changes["bases"]["removed"]
        or changes["bases"]["changed"]
    )
    changes["wording_only"] = not structural
    if changes["wording_only"] and changes["stem"]["changed"]:
        changes["summary"].append("仅题干措辞变化，限定条件和答案依据未变")

    if semantic_ids or changes["bases"]["added"] or changes["bases"]["removed"]:
        changes["answer_impact"] = "definite"
    elif added_condition_ids or removed_condition_ids or unknown_ids or changes["objective"]["changed"]:
        changes["answer_impact"] = "possible"
    elif changes["bases"]["changed"]:
        changes["answer_impact"] = "possible"
    else:
        changes["answer_impact"] = "none"
    return changes


def _basis_signature(basis):
    return (
        basis.get("conclusion", ""),
        basis.get("evidence", ""),
        tuple(basis.get("condition_ids", ())),
    )


def _basis_wording_only(previous, current):
    """判断答案依据是否只有措辞变化。

    结论和依据文本按忽略标点、空白和大小写的方式比较，依赖条件集合必须
    完全一致。这样「比较分子即可。」改成「比较分子即可!」等调整仍可沿用
    依据，而结论数值或依赖条件被改动时必须重新确认。
    """

    if tuple(previous.get("condition_ids", ())) != tuple(
        current.get("condition_ids", ())
    ):
        return False
    return (
        surface_key(previous.get("conclusion", ""))
        == surface_key(current.get("conclusion", ""))
        and surface_key(previous.get("evidence", ""))
        == surface_key(current.get("evidence", ""))
    )


def _evaluate_inherited_basis(basis, changes, source_unknown=False):
    """判断一个未修改的继承答案依据是否仍成立。

    返回 ``(status, determinate, affected_by, reason)``。
    """

    references = list(basis.get("condition_ids", ()))
    affected_by = []
    unknown_refs = []
    if source_unknown:
        return (
            NEEDS_REVIEW,
            INDETERMINATE,
            references,
            "来源版本缺失或不可解析，无法确认原答案依据是否成立",
        )

    removed = {entry["condition_id"] for entry in changes["conditions"]["removed"]}
    added = {entry["condition_id"] for entry in changes["conditions"]["added"]}
    changed = {
        entry["condition_id"]: entry
        for entry in changes["conditions"]["changed"]
    }
    previously_present = (
        set(removed)
        | set(changed)
        | set(changes["conditions"]["unchanged"])
    )
    currently_present = (
        set(added)
        | set(changed)
        | set(changes["conditions"]["unchanged"])
    )

    for condition_id in references:
        if condition_id in removed:
            affected_by.append(condition_id)
        elif condition_id in changed:
            kind = changed[condition_id]["change"]
            if kind == _SEMANTIC:
                affected_by.append(condition_id)
            elif kind == _UNKNOWN:
                affected_by.append(condition_id)
                unknown_refs.append(condition_id)
            elif kind == _WORDING:
                continue
        elif condition_id in added:
            # 新声明的依赖本身不是问题；但如果依据文本没变却开始依赖新条件，
            # 说明依赖关系可能不完整，需要人工确认。
            continue
        elif (
            condition_id not in previously_present
            and condition_id not in currently_present
        ):
            # 既不在来源版本也不在当前版本中，无法判断依赖关系。
            unknown_refs.append(condition_id)
            affected_by.append(condition_id)

    if affected_by:
        if unknown_refs:
            return (
                NEEDS_REVIEW,
                INDETERMINATE,
                affected_by,
                "答案依据依赖的条件无法判定是否变化",
            )
        if removed & set(references):
            return (
                STALE,
                DETERMINATE,
                affected_by,
                "答案依据依赖的条件已被删除，不能沿用原结论",
            )
        return (
            STALE,
            DETERMINATE,
            affected_by,
            "答案依据依赖的限定值已改变，不能沿用原结论",
        )

    if changes["objective"]["changed"]:
        return (
            NEEDS_REVIEW,
            INDETERMINATE,
            [],
            "课程目标变化，原答案依据是否成立无法判定",
        )

    scope_changed = sorted(added | removed)
    significant_change = sorted(
        condition_id
        for condition_id, entry in changed.items()
        if entry["change"] != _WORDING
    )
    if significant_change and not references:
        return (
            NEEDS_REVIEW,
            INDETERMINATE,
            significant_change,
            "限定条件发生变化，答案依据未声明依赖关系，无法判定",
        )
    if scope_changed:
        if not references:
            return (
                NEEDS_REVIEW,
                INDETERMINATE,
                scope_changed,
                "条件范围发生变化，答案依据未声明依赖关系，无法判定",
            )
        return (
            NEEDS_REVIEW,
            INDETERMINATE,
            scope_changed,
            "题目条件范围发生变化，未声明受影响的答案依据需要重新确认",
        )

    # 仅条件表述变化且限定值相同，或题干/标签变化。
    return (
        RETAINED,
        DETERMINATE,
        [],
        "限定条件语义未变，原答案依据仍成立",
    )


def _review_key(review):
    return (review.get("reviewed_at", ""), review.get("review_id", ""))


def _latest_review(reviews):
    if not reviews:
        return None
    return sorted(reviews, key=_review_key)[-1]


def _is_approved(review):
    return bool(review) and review.get("decision") == "approved"


def _confirmable_basis_ids(review, basis_ids):
    """返回复核实际确认的答案依据。

    只有 ``approved`` 复核才确认依据；未列出 ``confirmed_basis_ids`` 时表示
    整题通过，确认该修订的全部依据。``inconclusive`` 等结论不确认任何依据。
    """

    if not review or review.get("decision") != "approved":
        return set()
    confirmed = set(review.get("confirmed_basis_ids", ()))
    if confirmed:
        return confirmed & set(basis_ids)
    return set(basis_ids)


def evaluate_bases(current, parent, changes, current_review, parent_review):
    """计算每个当前答案依据的状态。

    当前修订的显式复核优先；没有显式复核时，只把上一修订中仍未受影响、且
    上一修订已通过的答案依据继续沿用。
    """

    current_bases = list(current.get("answer_bases", ()))
    parent_bases = _index(parent.get("answer_bases", ()) if parent else (), "basis_id")
    changed_ids = {entry["basis_id"] for entry in changes["bases"]["changed"]}
    current_ids = {basis["basis_id"] for basis in current_bases}
    source_issue = changes.get("source_issue", "")
    carry_possible = (
        parent is not None
        and not source_issue
        and _is_approved(parent_review)
        and parent_review.get("carry_forward", True)
    )
    parent_confirmed = _confirmable_basis_ids(
        parent_review, [basis["basis_id"] for basis in parent_bases.values()]
    )
    current_confirmed = _confirmable_basis_ids(current_review, current_ids)

    results = []
    for basis in current_bases:
        basis_id = basis["basis_id"]
        match = parent_bases.get(basis_id)
        if match is None and basis.get("source_basis_id"):
            match = parent_bases.get(basis["source_basis_id"])
        inherited = match is not None and match["basis_id"] not in changed_ids
        if match is not None and match["basis_id"] in changed_ids:
            inherited = False

        if current_review is not None:
            if basis_id in current_confirmed:
                results.append(
                    {
                        **basis,
                        "status": CONFIRMED,
                        "determinacy": DETERMINATE,
                        "carried_forward": False,
                        "needs_reconfirmation": False,
                        "affected_by": [],
                        "reason": "当前修订已人工复核确认",
                    }
                )
            else:
                if inherited or source_issue:
                    status, determinacy, affected_by, reason = _evaluate_inherited_basis(
                        basis, changes, source_unknown=source_issue and not inherited
                    )
                else:
                    status, determinacy, affected_by, reason = (
                        NEEDS_REVIEW,
                        DETERMINATE,
                        [],
                        "答案依据已修改或新增，需要人工复核",
                    )
                if status != STALE:
                    status = NEEDS_REVIEW
                    if current_review.get("decision") == "approved":
                        reason = "当前复核未确认该答案依据：" + reason
                results.append(
                    {
                        **basis,
                        "status": status,
                        "determinacy": determinacy,
                        "carried_forward": False,
                        "needs_reconfirmation": True,
                        "affected_by": affected_by,
                        "reason": reason,
                    }
                )
            continue

        if not inherited:
            if source_issue:
                status, determinacy, affected_by, reason = _evaluate_inherited_basis(
                    basis, changes, source_unknown=True
                )
            else:
                status, determinacy, affected_by, reason = (
                    NEEDS_REVIEW,
                    DETERMINATE,
                    [],
                    "答案依据已修改或新增，需要人工复核",
                )
            results.append(
                {
                    **basis,
                    "status": status,
                    "determinacy": determinacy,
                    "carried_forward": False,
                    "needs_reconfirmation": True,
                    "affected_by": affected_by,
                    "reason": reason,
                }
            )
            continue

        status, determinacy, affected_by, reason = _evaluate_inherited_basis(
            basis, changes
        )
        carried = False
        if (
            carry_possible
            and match is not None
            and match["basis_id"] in parent_confirmed
            and status == RETAINED
        ):
            status = CONFIRMED
            carried = True
            reason = "限定条件语义未变，沿用上一修订的已确认依据"
        results.append(
            {
                **basis,
                "status": status,
                "determinacy": determinacy,
                "carried_forward": carried,
                "needs_reconfirmation": status != CONFIRMED,
                "affected_by": affected_by,
                "reason": reason,
            }
        )
    return results


def _question_status(current_review, basis_results):
    if current_review is not None and current_review.get("decision") in (
        "rejected",
        "needs_changes",
    ):
        return current_review["decision"]
    if not basis_results:
        return "missing_answer_basis"
    if any(result["status"] == STALE for result in basis_results):
        return "blocked"
    if current_review is not None and current_review.get("decision") == "inconclusive":
        return "pending_review"
    if any(result["status"] != CONFIRMED for result in basis_results):
        return "pending_review"
    if current_review is not None and current_review.get("decision") == "approved":
        return "approved"
    if all(result.get("carried_forward") for result in basis_results):
        return "approved"
    return "pending_review"


def build_lineage(current, parent, changes, reviews, parent_reviews, ancestors=()):
    """生成一题的来源、修改点、依据状态与可发布性。

    ``reviews`` 只包含当前修订的复核记录；``parent_reviews`` 包含直接来源
    版本的复核记录。
    """

    current_review = _latest_review(reviews)
    parent_review = _latest_review(parent_reviews)
    basis_results = evaluate_bases(
        current, parent, changes, current_review, parent_review
    )
    pending_basis_ids = [
        result["basis_id"]
        for result in basis_results
        if result["status"] != CONFIRMED
    ]
    stale_basis_ids = [
        result["basis_id"]
        for result in basis_results
        if result["status"] == STALE
    ]
    indeterminate_basis_ids = [
        result["basis_id"]
        for result in basis_results
        if result["determinacy"] == INDETERMINATE
    ]
    status = _question_status(current_review, basis_results)
    source_issue = changes.get("source_issue", "")
    if source_issue:
        status = "pending_review"
    publishable = status == "approved" and not pending_basis_ids and not source_issue

    return {
        "question_id": current["question_id"],
        "revision": current["revision"],
        "stem": current["stem"],
        "objective": current.get("objective", ""),
        "difficulty": current.get("difficulty", ""),
        "tags": list(current.get("tags", ())),
        "source_version": (
            {
                "question_id": parent["question_id"],
                "revision": parent["revision"],
            }
            if parent
            else None
        ),
        "is_adaptation": bool(
            parent and parent["question_id"] != current["question_id"]
        ),
        "declared_source": dict(current.get("derived_from"))
        if current.get("derived_from")
        else None,
        "ancestors": list(ancestors),
        "changes": changes,
        "answer_bases": basis_results,
        "needs_reconfirmation": pending_basis_ids,
        "stale_basis_ids": stale_basis_ids,
        "indeterminate_basis_ids": indeterminate_basis_ids,
        "review": current_review,
        "carried_review": (
            parent_review
            if parent is not None
            and parent_review is not None
            and parent_review.get("revision") == parent.get("revision")
            and parent_review.get("carry_forward", True)
            and _is_approved(parent_review)
            else None
        ),
        "review_required": bool(pending_basis_ids)
        or bool(source_issue)
        or not (
            _is_approved(current_review)
            or (
                parent_review is not None
                and _is_approved(parent_review)
                and all(
                    result.get("carried_forward")
                    for result in basis_results
                )
                and basis_results
            )
        ),
        "status": status,
        "publishable": publishable,
    }


def find_duplicate_groups(questions: Iterable[dict]):
    """按「题干 + 课程目标」归组，并显式列出不同目标下的同题干情况。

    这里只产生复核线索，从不自动合并题目；同一题干来自不同课程目标时即使
    文本完全一致也分属不同组。
    """

    latest = {}
    for question in questions:
        question_id = question["question_id"]
        previous = latest.get(question_id)
        if previous is None or question["revision"] > previous["revision"]:
            latest[question_id] = question

    by_stem = {}
    for question in latest.values():
        key = surface_key(question.get("stem", ""))
        if not key:
            continue
        by_stem.setdefault(key, []).append(question)

    groups = []
    cross_objective = []
    for key, entries in sorted(by_stem.items()):
        by_objective = {}
        for entry in entries:
            by_objective.setdefault(entry.get("objective", ""), []).append(entry)
        if len(by_objective) > 1:
            cross_objective.append(
                {
                    "stem_key": key,
                    "stem": entries[0].get("stem", ""),
                    "objectives": sorted(by_objective),
                    "groups": [
                        {
                            "objective": objective,
                            "question_ids": sorted(
                                entry["question_id"] for entry in members
                            ),
                            "revisions": sorted(
                                entry["revision"] for entry in members
                            ),
                        }
                        for objective, members in sorted(by_objective.items())
                    ],
                    "auto_merge": False,
                    "reason": "题干相同但课程目标不同，必须分别处理",
                }
            )
        for objective, members in sorted(by_objective.items()):
            if len(members) < 2:
                continue
            groups.append(
                {
                    "stem_key": key,
                    "stem": members[0].get("stem", ""),
                    "objective": objective,
                    "question_ids": sorted(entry["question_id"] for entry in members),
                    "revisions": sorted(entry["revision"] for entry in members),
                    "auto_merge": False,
                    "reason": "题干与课程目标相同，仍需人工确认是否为重复题",
                }
            )
    return {
        "groups": groups,
        "same_stem_different_objectives": cross_objective,
        "auto_merged": [],
        "notes": "同一题干可能对应不同课程目标，工具不会自动合并任何题目",
    }
