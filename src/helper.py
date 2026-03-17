import os
import shutil
from pathlib import Path
from git import Repo
from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings  # ✅ HuggingFace

# clone any github repositories 
def repo_ingestion(repo_url, repo_path="repo"):
    # Ensure we always index the latest repository content for this repo path.
    if os.path.isdir(repo_path):
        shutil.rmtree(repo_path, ignore_errors=True)
    os.makedirs(repo_path, exist_ok=True)
    Repo.clone_from(repo_url, to_path=repo_path)

# Loading repositories as documents
def load_repo(repo_path):
    documents = []
    repo_root = Path(repo_path)

    # Include both source code and README/docs files for repo-level questions.
    include_suffixes = {".py", ".md", ".txt", ".rst"}
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



