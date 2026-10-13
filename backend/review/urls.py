from django.urls import path

from review import views

urlpatterns = [
    path("auth/csrf", views.CsrfView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/logout", views.LogoutView.as_view()),
    path("auth/me", views.MeView.as_view()),
    path("review/queue", views.QueueView.as_view()),
    path("review/next", views.NextView.as_view()),
    path("review/stats", views.StatsView.as_view()),
    path("review/documents/<uuid:document_id>", views.ReviewDocumentView.as_view()),
    path("review/documents/<uuid:document_id>/decision", views.DecisionView.as_view()),
    path("rules", views.RulesView.as_view()),
]
