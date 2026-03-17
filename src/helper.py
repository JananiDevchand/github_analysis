import os
import shutil
from pathlib import Path
from urllib.parse import urlparse
from git import Repo
from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings  # ✅ HuggingFace


def normalize_repo_url(repo_url):
    """Normalize user-provided GitHub URL into a cloneable HTTPS URL."""
    value = (repo_url or "").strip()
    if not value:
        raise ValueError("Repository URL is required.")

    if value.startswith("git@github.com:"):
        value = value.replace("git@github.com:", "https://github.com/", 1)

    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/")
    if host not in {"github.com", "www.github.com"}:
        raise ValueError("Only GitHub repository URLs are supported.")

    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError("Use a repository URL like https://github.com/owner/repo")

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise ValueError("Use a repository URL like https://github.com/owner/repo")

    return f"https://github.com/{owner}/{repo}.git"

# clone any github repositories 
def repo_ingestion(repo_url, repo_path="repo"):
    # Ensure we always index the latest repository content for this repo path.
    if os.path.isdir(repo_path):
        shutil.rmtree(repo_path, ignore_errors=True)
    os.makedirs(repo_path, exist_ok=True)
    normalized_url = normalize_repo_url(repo_url)
    if shutil.which("git") is None:
        raise RuntimeError("Git executable not found on server.")
    Repo.clone_from(normalized_url, to_path=repo_path)

# Loading repositories as documents
def load_repo(repo_path):
    documents = []
    repo_root = Path(repo_path)

    # Include both source code and README/docs files for repo-level questions.
    include_suffixes = {
        ".py", ".ipynb", ".md", ".txt", ".rst", ".json", ".yaml", ".yml",
        ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp",
        ".h", ".hpp", ".cs", ".php", ".rb", ".kt", ".swift", ".scala", ".sql",
        ".html", ".css", ".sh", ".ps1", ".toml", ".ini", ".cfg", ".xml",
    }
    for file_path in repo_root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in include_suffixes:
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="latin-1", errors="ignore")

        if content.strip():
            documents.append(
                Document(
                    page_content=content,
                    metadata={"source": str(file_path).replace("\\", "/")},
                )
            )

    return documents

# Creating text chunks 
def text_splitter(documents):
    documents_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=200,
    )
    text_chunks = documents_splitter.split_documents(documents)
    return text_chunks

# loading embeddings model
def load_embedding():
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")  # ✅ HuggingFace embedding
    return embeddings



