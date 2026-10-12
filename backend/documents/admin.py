from django.contrib import admin

from documents.models import Document, Extraction, Job


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin[Document]):
    list_display = ["filename", "tenant", "status", "page_count", "created_at"]
    list_filter = ["status", "tenant"]
    search_fields = ["filename", "sha256"]


@admin.register(Job)
class JobAdmin(admin.ModelAdmin[Job]):
    list_display = ["document", "status", "attempts", "run_after", "finished_at"]
    list_filter = ["status"]


@admin.register(Extraction)
class ExtractionAdmin(admin.ModelAdmin[Extraction]):
    list_display = ["document", "pipeline_version", "confidence", "ocr_ms", "extraction_ms", "created_at"]
