# 题库题干溯源器

题库题干溯源器用于处理本地合成教研文本，保存来源版本、文本片段和处理记录，供校内复核使用。

除文本导入外，题目库还保存题目版本、限定条件、答案依据和人工复核记录，用于判断改编题或修订题的原答案与解析是否仍然成立。判定基于显式记录的条件和依赖关系，不用题干相似度代替语义判断。

## 环境

需要 Python 3.11 或更新版本。应用运行不依赖第三方包；运行测试和构建前，安装固定版本的开发工具：`python -m pip install -r requirements-dev.txt`。

## 文本处理

执行 `PYTHONPATH=src python -m nlp_question_bank_lineage.cli ingest fixtures/records.json` 导入演练记录，再执行 `PYTHONPATH=src python -m nlp_question_bank_lineage.cli list` 查看当前文本处理结果。运行数据保存在 `var/records.json`。

## 题目版本与溯源

题目库默认保存在 `var/questions.json`（可用 `--question-state` 指定）。每个题目版本包含：

| 字段 | 说明 |
| --- | --- |
| `question_id` / `revision` | 题目身份与修订号，版本只追加、不覆盖 |
| `stem` | 题干，导入时做文本规范化 |
| `objective` | 课程目标；同题干不同目标不会被合并 |
| `conditions[]` | 限定条件，`condition_id` 稳定标识，`value` 保存可比较的限定值 |
| `answer_bases[]` | 答案依据，`conclusion` 是结论，`condition_ids` 声明该结论依赖哪些条件 |
| `derived_from` | 改编题的来源版本 `{question_id, revision}`；同题新修订可省略 |
| `tags` / `difficulty` / `context` | 原有标签与语境 |

复核记录单独保存在同一文件的 `reviews` 中，绑定 `question_id` 和 `revision`，`decision` 取 `approved` / `rejected` / `needs_changes` / `inconclusive`，`carry_forward` 表示下一修订在条件未受影响时是否可沿用，`confirmed_basis_ids` 可只确认部分答案依据。

```bash
# 导入题目版本与复核记录
PYTHONPATH=src python -m nlp_question_bank_lineage.cli ingest-questions fixtures/questions.json

# 查看每题最新版本的状态
PYTHONPATH=src python -m nlp_question_bank_lineage.cli list-questions
PYTHONPATH=src python -m nlp_question_bank_lineage.cli list-questions --status blocked

# 从一题查看来源版本、修改点和待重新确认的结论
PYTHONPATH=src python -m nlp_question_bank_lineage.cli trace --question fraction-compare
PYTHONPATH=src python -m nlp_question_bank_lineage.cli trace --question fraction-compare --revision 1

# 待重新确认清单与重复题干线索
PYTHONPATH=src python -m nlp_question_bank_lineage.cli pending
PYTHONPATH=src python -m nlp_question_bank_lineage.cli duplicates
```

### 判定规则

- **仅措辞变化**：题干、条件或答案依据只有标点、空白、大小写或表述调整，且条件的 `value` 相同、答案依据的依赖条件未变时，原依据继续成立；上一修订已通过且允许沿用时，状态记为 `confirmed` 并标注 `carried_forward`。
- **限定条件变化**：依赖该条件的答案依据标记为 `stale`，题目状态为 `blocked`，不能发布，除非当前修订经人工复核重新确认。
- **无法判定**：条件缺少可比较的 `value`、答案依据未声明依赖、新增或删除条件但依据未声明关系、课程目标变化，或声明的来源版本缺失时，依据保持 `needs_review`（`determinacy: indeterminate`），题目保持 `pending_review`，不因复核勾选而自动通过。
- **答案依据变化**：结论或依据文本变化、依据新增时，必须由当前修订的复核显式确认。
- **版本不可覆盖**：已有修订内容不同会拒绝导入，必须使用新修订号；复核只能引用已存在的版本和答案依据。

`trace` 输出包含 `source_version`、`ancestors`、`changes`（逐项列出新增/删除/修改的条件与依据）、`answer_bases`（含 `status`、`determinacy`、`affected_by`、`reason`）、`needs_reconfirmation`、`stale_basis_ids`、`indeterminate_basis_ids`、`review`、`version_history`、`status` 和 `publishable`。

`duplicates` 只给出复核线索：同一题干来自不同课程目标时会分列在 `same_stem_different_objectives` 中，`auto_merged` 始终为空。

## 测试

执行 `python -m pytest -q` 检查文本规范化、记录处理、状态读取、本地持久化，以及版本溯源、条件变化、复核沿用和可发布性判定。
