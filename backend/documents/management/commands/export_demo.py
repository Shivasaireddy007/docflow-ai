import base64
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from documents.models import Document
from documents.storage import get_storage
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Save a tenant's processed documents (files, OCR and fields) as the public demo's data."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("tenant", help="Tenant slug")
        parser.add_argument("--out", type=Path, default=Path("demo/documents.json"))

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.filter(slug=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"No tenant {options['tenant']!r}.")
        documents = []
        for document in Document.objects.filter(tenant=tenant).order_by("created_at"):
            extraction = document.latest_extraction()
            if extraction is None:
                continue
            documents.append(
                {
                    "filename": document.filename,
                    "content_type": document.content_type,
                    "page_count": document.page_count,
                    "file": base64.b64encode(get_storage().get(document.storage_key)).decode(),
                    "extraction": {
                        "pipeline_version": extraction.pipeline_version,
                        "ocr_text": extraction.ocr_text,
                        "fields": extraction.fields,
                        "line_items": extraction.line_items,
                        "confidence": extraction.confidence,
                        "ocr_ms": extraction.ocr_ms,
                        "extraction_ms": extraction.extraction_ms,
                    },
                }
            )
        options["out"].parent.mkdir(parents=True, exist_ok=True)
        options["out"].write_text(json.dumps({"documents": documents}, indent=1))
        self.stdout.write(f"Saved {len(documents)} documents to {options['out']}.")
