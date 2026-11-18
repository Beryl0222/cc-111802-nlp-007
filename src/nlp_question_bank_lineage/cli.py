import argparse
import json
import sys
from pathlib import Path

from .question_workflow import QuestionWorkflow
from .repository import QuestionRepository, RecordRepository
from .workflow import TextWorkflow


ACTIONS = (
    "ingest",
    "list",
    "ingest-questions",
    "list-questions",
    "trace",
    "pending",
    "duplicates",
    "reviews",
)


def _build_parser():
    parser = argparse.ArgumentParser(description="本地教研文本处理与题库题干溯源工具")
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("path", nargs="?", default=None)
    parser.add_argument("--state", default="var/records.json")
    parser.add_argument(
        "--question-state",
        default=None,
        help="题目版本库路径，默认与 --state 同目录下的 questions.json",
    )
    parser.add_argument("--question", default=None, help="题目编号")
    parser.add_argument("--revision", type=int, default=None, help="修订号")
    parser.add_argument("--status", default=None, help="按状态筛选")
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    is_question_action = args.action in (
        "ingest-questions",
        "list-questions",
        "trace",
        "pending",
        "duplicates",
        "reviews",
    )
    if is_question_action:
        if not args.question_state:
            args.question_state = str(
                Path(args.state).parent / "questions.json"
            )
        workflow = QuestionWorkflow(QuestionRepository(args.question_state))
        if args.action == "ingest-questions":
            path = args.path or "fixtures/questions.json"
            result = workflow.ingest(json.loads(Path(path).read_text(encoding="utf-8")))
        elif args.action == "list-questions":
            result = workflow.list_questions(args.question, args.status)
        elif args.action == "trace":
            if not args.question:
                parser.error("trace 需要 --question")
            result = workflow.trace(args.question, args.revision)
        elif args.action == "pending":
            result = workflow.pending_reconfirmations(args.question)
        elif args.action == "duplicates":
            result = workflow.duplicates()
        else:
            result = workflow.list_reviews(args.question)
    else:
        workflow = TextWorkflow(RecordRepository(args.state))
        if args.action == "ingest":
            path = args.path or "fixtures/records.json"
            result = workflow.ingest(json.loads(Path(path).read_text(encoding="utf-8")))
        else:
            result = workflow.list_records()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
