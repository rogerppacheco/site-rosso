from django.urls import path
from .views import UploadOsabView

urlpatterns = [
    path('upload/', UploadOsabView.as_view(), name='osab-upload'),
]