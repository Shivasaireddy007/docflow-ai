"""AWS clients and resource names for the Lambda steps, from the environment Terraform sets."""

import os
import time
from functools import cache
from typing import Any

import boto3


@cache
def s3() -> Any:
    return boto3.client("s3")


@cache
def dynamodb() -> Any:
    return boto3.resource("dynamodb")


@cache
def secrets() -> Any:
    return boto3.client("secretsmanager")


def bucket() -> str:
    return os.environ["DOCUMENTS_BUCKET"]


def results_table() -> Any:
    return dynamodb().Table(os.environ["RESULTS_TABLE"])


def cache_table() -> Any:
    return dynamodb().Table(os.environ["CACHE_TABLE"])


class DynamoStore:
    """The result cache's store on AWS: items expire through DynamoDB's TTL."""

    def __init__(self, table: Any) -> None:
        self.table = table

    def get(self, key: str) -> str | None:
        item = self.table.get_item(Key={"key": key}).get("Item")
        if item is None or int(item.get("expires_at", 0)) < time.time():
            return None  # TTL deletion lags; an expired item is a miss
        return str(item["value"])

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.table.put_item(Item={"key": key, "value": value, "expires_at": int(time.time()) + ttl_seconds})
