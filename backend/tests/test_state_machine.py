"""The state machine itself, in AWS Step Functions Local with every step mocked
(infra/statemachine/mock-config.json). Runs in CI; locally:

    docker run -p 8083:8083 -e SFN_MOCK_CONFIG=/mock.json \\
      -v $PWD/infra/statemachine/mock-config.json:/mock.json amazon/aws-stepfunctions-local
    SFN_LOCAL_URL=http://localhost:8083 uv run pytest tests/test_state_machine.py
"""

import os
import re
import time
from pathlib import Path
from typing import Any

import boto3
import pytest

URL = os.environ.get("SFN_LOCAL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="needs Step Functions Local (SFN_LOCAL_URL)")

DEFINITION = Path(__file__).resolve().parents[2] / "infra" / "statemachine" / "pipeline.asl.json"
ACCOUNT = "123456789012"


def render() -> str:
    """What Terraform's templatefile produces, with short retry waits."""
    values = {
        "model_retry_seconds": "1",
        "results_table": "docflow-results",
        "dead_letter_queue_url": f"https://sqs.us-east-1.amazonaws.com/{ACCOUNT}/docflow-dead-letters",
    }
    return re.sub(
        r"\$\{(\w+)\}",
        lambda m: values.get(
            m.group(1), f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:docflow-{m.group(1)}:live"
        ),
        DEFINITION.read_text(),
    )


@pytest.fixture(scope="module")
def machine() -> tuple[Any, str]:
    client = boto3.client(
        "stepfunctions", endpoint_url=URL, region_name="us-east-1",
        aws_access_key_id="local", aws_secret_access_key="local",
    )  # fmt: skip
    arn = client.create_state_machine(
        name="docflow", definition=render(), roleArn=f"arn:aws:iam::{ACCOUNT}:role/docflow"
    )["stateMachineArn"]
    return client, arn


def execute(machine: tuple[Any, str], case: str) -> tuple[str, list[dict[str, Any]]]:
    client, arn = machine
    execution = client.start_execution(
        stateMachineArn=f"{arn}#{case}",
        input='{"bucket": "docflow-documents", "key": "tenants/acme/uploads/r.png"}',
    )["executionArn"]
    for _ in range(120):
        status = client.describe_execution(executionArn=execution)["status"]
        if status != "RUNNING":
            break
        time.sleep(0.5)
    events = client.get_execution_history(executionArn=execution, maxResults=1000)["events"]
    return status, events


def entered(events: list[dict[str, Any]]) -> list[str]:
    return [e["stateEnteredEventDetails"]["name"] for e in events if "stateEnteredEventDetails" in e]


def task_failures(events: list[dict[str, Any]]) -> int:
    """Failed task attempts in the execution, retries included (each mock fails only one step)."""
    return sum(e["type"] == "TaskFailed" for e in events)


def test_a_receipt_goes_from_upload_to_decision(machine: tuple[Any, str]) -> None:
    status, events = execute(machine, "HappyPath")

    assert status == "SUCCEEDED"
    assert entered(events) == ["Prepare", "Already processed?", "OCR", "Extract fields", "Decide", "Done"]


def test_a_file_already_processed_stops_early(machine: tuple[Any, str]) -> None:
    status, events = execute(machine, "AlreadyProcessed")

    assert status == "SUCCEEDED"
    assert "OCR" not in entered(events)


def test_a_busy_model_is_retried_until_it_answers(machine: tuple[Any, str]) -> None:
    status, events = execute(machine, "BusyModelRecovers")

    assert status == "SUCCEEDED"
    assert task_failures(events) == 2


def test_a_model_that_keeps_failing_ends_in_the_dead_letter_queue(machine: tuple[Any, str]) -> None:
    status, events = execute(machine, "ModelKeepsFailing")

    assert status == "FAILED"
    assert task_failures(events) == 5, "the first try and four retries (MaxAttempts counts retries)"
    assert entered(events)[-4:] == ["Failed?", "Mark failed", "Send to dead-letter queue", "Failed"]


def test_an_unusable_upload_fails_at_once_without_retries(machine: tuple[Any, str]) -> None:
    status, events = execute(machine, "UnusableUpload")

    assert status == "FAILED"
    assert task_failures(events) == 1
    assert "Mark failed" not in entered(events), "nothing was claimed, so there is no record to mark"
    assert "Send to dead-letter queue" in entered(events)
