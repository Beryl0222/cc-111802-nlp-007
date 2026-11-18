import json
from pathlib import Path


class RecordRepository:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(value, dict) or not isinstance(value.get("records"), list):
            raise ValueError("记录库格式无效")
        return value["records"]

    def replace(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


class QuestionRepository:
    """保存全部题目版本与复核记录。

    版本只追加、不覆盖：同一 ``question_id`` 的旧修订始终可追溯，复核记录也
    独立保存，避免题面被新版本覆盖后失去来源。
    """

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"versions": [], "reviews": []}
        if not isinstance(value, dict):
            raise ValueError("题目库格式无效")
        versions = value.get("versions", [])
        reviews = value.get("reviews", [])
        if not isinstance(versions, list) or not isinstance(reviews, list):
            raise ValueError("题目库格式无效")
        return {"versions": versions, "reviews": reviews}

    def replace(self, versions, reviews):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "versions": sorted(
                versions, key=lambda row: (row["question_id"], row["revision"])
            ),
            "reviews": sorted(
                reviews, key=lambda row: (row["question_id"], row["revision"])
            ),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)
