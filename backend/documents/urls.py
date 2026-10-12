from rest_framework.routers import SimpleRouter

from documents.views import DocumentViewSet

router = SimpleRouter(trailing_slash=False)
router.register("documents", DocumentViewSet, basename="document")
urlpatterns = router.urls
