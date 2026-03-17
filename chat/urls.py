from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("chatbot", views.git_repo, name="git_repo"),
    path("get", views.chat, name="chat"),
    path("repos", views.repositories, name="repositories"),
    path("switch_repo", views.switch_repo, name="switch_repo"),
]
