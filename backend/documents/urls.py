from django.urls import path
from rest_framework.routers import SimpleRouter

from documents.callback import PipelineResultView
from documents.views import DocumentViewSet

router = SimpleRouter(trailing_slash=False)
router.register("documents", DocumentViewSet, basename="document")
urlpatterns = [path("internal/pipeline-results", PipelineResultView.as_view()), *router.urls]
