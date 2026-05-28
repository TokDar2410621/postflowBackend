"""RAG memory URLs — mount on ``/api/rag/`` in your project."""
from django.urls import path

from .views import FeedbackView, IndexView, RetrieveView


app_name = "rag_memory_pgvector"

urlpatterns = [
    path("index/", IndexView.as_view(), name="rag-index"),
    path("retrieve/", RetrieveView.as_view(), name="rag-retrieve"),
    path("feedback/", FeedbackView.as_view(), name="rag-feedback"),
]
