import argparse
import json
from pathlib import Path

from app.config import settings
from app.llm_client import OpenAIExtractionClient
from app.services.extraction_service import extract_with_retry


DEFAULT_THRESHOLD = 0.80


def run_eval(dataset_path: Path, threshold: float) -> int:
    client = OpenAIExtractionClient(
        api_key=settings.openai_api_key or "",
        model=settings.openai_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    records = json.loads(dataset_path.read_text())
    earned = 0
    possible = len(records) * 3

    for index, record in enumerate(records, start=1):
        attributes = extract_with_retry(client, record["message"])
        kind_match = any(attribute["kind"] == record["expected_kind"] for attribute in attributes)
        restricted_match = bool(attributes) and all(
            attribute["restricted"] == record["expected_restricted"] for attribute in attributes
        )
        keyword_match = any(
            keyword.lower() in attribute["text"].lower()
            for keyword in record["expected_keywords"]
            for attribute in attributes
        )
        record_score = sum((kind_match, restricted_match, keyword_match))
        earned += record_score
        print(
            f"record={index} kind={kind_match} restricted={restricted_match} "
            f"keyword={keyword_match} score={record_score}/3 attributes={json.dumps(attributes)}"
        )

    overall = earned / possible if possible else 0.0
    print(f"overall={earned}/{possible} score={overall:.3f} threshold={threshold:.3f}")
    return 0 if overall >= threshold else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate real LLM attribute extraction")
    parser.add_argument("--dataset", type=Path, default=Path("eval/golden_set.json"))
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()
    return run_eval(args.dataset, args.threshold)


if __name__ == "__main__":
    raise SystemExit(main())
