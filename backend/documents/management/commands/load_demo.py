import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from documents.models import Document, Extraction
from documents.storage import document_key, get_storage
from review import audit
from review.decisions import decide_automatically
from tenants.models import ApiKey, Membership, Tenant

DEMO_PASSWORD = "demo-password"  # noqa: S105  (the public demo login, shown on its sign-in page)


class Command(BaseCommand):
    help = (
        "Empty the database and load the public demo: receipts already read by the models, decided "
        "by the default rules, and a reviewer login (demo / demo-password)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--data", type=Path, default=Path("demo/documents.json"))

    def handle(self, *args: Any, **options: Any) -> None:
        data = json.loads(options["data"].read_text())
        call_command("flush", interactive=False, verbosity=0)  # TRUNCATE: the audit trigger allows it

        with transaction.atomic():
            tenant = Tenant.objects.create(name="Demo Expenses", slug="demo")
            ApiKey.issue(tenant, "demo")
            reviewer = User.objects.create_user("demo", password=DEMO_PASSWORD)
            Membership.objects.create(user=reviewer, tenant=tenant, role=Membership.Role.ADMIN)

            for item in data["documents"]:
                content = base64.b64decode(item["file"])
                sha256 = hashlib.sha256(content).hexdigest()
                key = document_key(tenant.id, sha256)
                get_storage().put(key, content, item["content_type"])
                document = Document.objects.create(
                    tenant=tenant,
                    sha256=sha256,
                    filename=item["filename"],
                    content_type=item["content_type"],
                    size_bytes=len(content),
                    page_count=item["page_count"],
                    storage_key=key,
                    status=Document.Status.PROCESSING,
                )
                audit.record(tenant, "api-key:demo", "uploaded", document, filename=document.filename)
                extraction = Extraction.objects.create(document=document, **item["extraction"])
                audit.record(
                    tenant,
                    audit.PIPELINE,
                    "extracted",
                    document,
                    pipeline_version=extraction.pipeline_version,
                    confidence=extraction.confidence,
                    ms=extraction.ocr_ms + extraction.extraction_ms,
                )
                decide_automatically(document, extraction)  # the rules, for real
        queue = Document.objects.filter(status=Document.Status.NEEDS_REVIEW).count()
        self.stdout.write(f"Loaded {len(data['documents'])} documents ({queue} waiting for review).")
