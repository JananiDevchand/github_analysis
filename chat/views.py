import os
import shutil
import subprocess
import sys
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAI
from langchain.memory import ConversationSummaryMemory
from langchain.chains import ConversationalRetrievalChain
from langchain_community.embeddings import HuggingFaceEmbeddings

from src.helper import repo_ingestion

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
load_dotenv()
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
if GOOGLE_API_KEY:
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY

REPOS_ROOT = Path(settings.BASE_DIR) / "repos"
VECTORS_ROOT = Path(settings.BASE_DIR) / "db"
REPOS_ROOT.mkdir(parents=True, exist_ok=True)
VECTORS_ROOT.mkdir(parents=True, exist_ok=True)


def _repo_paths(repo_id):
    return REPOS_ROOT / repo_id, VECTORS_ROOT / repo_id


def _build_qa_chain(db_path):
    """Create a fresh retrieval chain from the persisted vector store."""
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vectordb = Chroma(persist_directory=str(db_path), embedding_function=embeddings)
    llm = GoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)
    memory = ConversationSummaryMemory(llm=llm, memory_key="chat_history", return_messages=True)
    return ConversationalRetrievalChain.from_llm(
        llm,
        retriever=vectordb.as_retriever(search_type="mmr", search_kwargs={"k": 8}),
        memory=memory,
    )


# Cache QA chains by repo_id to support safe repo switching per session.
qa_by_repo = {}
META_FILE_NAME = ".codesphere.json"


def _meta_path(repo_id):
    repo_path, _ = _repo_paths(repo_id)
    return repo_path / META_FILE_NAME

def _write_repo_meta(repo_id, repo_url):
    meta = {
        "repo_id": repo_id,
        "repo_url": repo_url,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    _meta_path(repo_id).write_text(json.dumps(meta), encoding="utf-8")

def _read_repo_meta(repo_id):
    path = _meta_path(repo_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

def _list_available_repositories():
    repos = []
    for repo_dir in REPOS_ROOT.iterdir():
        if not repo_dir.is_dir():
            continue
        repo_id = repo_dir.name
        if not _repo_exists(repo_id):
            continue

        meta = _read_repo_meta(repo_id) or {}
        repo_url = meta.get("repo_url") or "Unknown repository"
        indexed_at = meta.get("indexed_at") or ""
        repos.append({"repo_id": repo_id, "repo_url": repo_url, "indexed_at": indexed_at})

    repos.sort(key=lambda item: item.get("indexed_at", ""), reverse=True)
    return repos


def _repo_exists(repo_id):
    repo_path, db_path = _repo_paths(repo_id)
    return repo_path.exists() and db_path.exists()


def _get_qa_chain(repo_id):
    if repo_id in qa_by_repo:
        return qa_by_repo[repo_id]
    _, db_path = _repo_paths(repo_id)
    if not db_path.exists():
        return None
    qa_by_repo[repo_id] = _build_qa_chain(db_path)
    return qa_by_repo[repo_id]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def index(request):
    """Render the main page."""
    return render(request, "index.html")


@csrf_exempt
def git_repo(request):
    """Index a GitHub repository."""
    user_input = ""
    if request.method == "POST":
        user_input = request.POST.get("question", "")
        if not user_input.strip():
            return JsonResponse({"error": "Repository URL is required."}, status=400)

        repo_id = uuid.uuid4().hex[:12]
        repo_path, db_path = _repo_paths(repo_id)

        try:
            repo_ingestion(user_input, repo_path=str(repo_path))
            # Rebuild vector DB with the same interpreter running Django.
            completed = subprocess.run(
                [
                    sys.executable,
                    "store_index.py",
                    "--repo-path",
                    str(repo_path),
                    "--db-path",
                    str(db_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            qa_by_repo[repo_id] = _build_qa_chain(db_path)
            request.session["active_repo_id"] = repo_id
            request.session["active_repo_url"] = user_input
            _write_repo_meta(repo_id, user_input)
            return JsonResponse({"response": str(user_input), "repo_id": repo_id})
        except Exception as exc:
            shutil.rmtree(repo_path, ignore_errors=True)
            shutil.rmtree(db_path, ignore_errors=True)

            error_message = str(exc)
            if isinstance(exc, subprocess.CalledProcessError):
                error_message = (exc.stderr or exc.stdout or str(exc)).strip()[:600]
            if not error_message:
                error_message = "Unexpected indexing error"

            return JsonResponse(
                {
                    "error": "Unable to index repository.",
                    "details": error_message,
                },
                status=400,
            )
    return JsonResponse({"response": str(user_input)})


@csrf_exempt
def repositories(request):
    """Return previously indexed repositories available on disk."""
    history = _list_available_repositories()
    active_repo_id = request.session.get("active_repo_id")
    if active_repo_id and not any(item.get("repo_id") == active_repo_id for item in history):
        request.session.pop("active_repo_id", None)
        request.session.pop("active_repo_url", None)
        active_repo_id = None
    elif not active_repo_id and history:
        active_repo_id = history[0]["repo_id"]
        request.session["active_repo_id"] = active_repo_id
        request.session["active_repo_url"] = history[0].get("repo_url", "")
    return JsonResponse({"active_repo_id": active_repo_id, "repositories": history})


@csrf_exempt
def switch_repo(request):
    """Switch active repository context for chat in current session."""
    repo_id = request.POST.get("repo_id", "")
    history = _list_available_repositories()
    match = next((item for item in history if item.get("repo_id") == repo_id), None)
    if not match:
        return JsonResponse({"error": "Repository not found in this session."}, status=404)

    request.session["active_repo_id"] = repo_id
    request.session["active_repo_url"] = match.get("repo_url", "")
    return JsonResponse({"repo_id": repo_id, "repo_url": match.get("repo_url", "")})


@csrf_exempt
def chat(request):
    """Answer a code question."""
    active_repo_id = request.session.get("active_repo_id")
    msg = request.POST.get("msg", "")

    if msg == "clear":
        if not active_repo_id:
            return HttpResponse("No active repository in this session.")
        # Keep indexed repositories on disk so users can switch back later.
        qa_by_repo.pop(active_repo_id, None)
        request.session.pop("active_repo_id", None)
        request.session.pop("active_repo_url", None)
        return HttpResponse("Active repository cleared for this session.")

    if not active_repo_id:
        return HttpResponse("Please index a repository first.")

    qa = _get_qa_chain(active_repo_id)
    if qa is None:
        return HttpResponse("No vector index found for this repository. Re-index and try again.")

    result = qa({"question": msg})
    return HttpResponse(str(result["answer"]))
