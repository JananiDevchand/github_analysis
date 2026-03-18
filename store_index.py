# store_index.py
import argparse
import os

from src.helper import load_repo, text_splitter, load_embedding
from langchain_community.vectorstores import Chroma

def build_index(repo_path, db_path):
	# Validate environment before proceeding
	if not os.environ.get("GOOGLE_API_KEY"):
		raise RuntimeError("GOOGLE_API_KEY environment variable is not set.")
	
	# Load documents from the selected repo path
	documents = load_repo(repo_path)
	if not documents:
		raise ValueError("No supported files found in repository to index.")
	text_chunks = text_splitter(documents)
	if not text_chunks:
		raise ValueError("Repository files were loaded, but no text chunks were created.")

	# Load HuggingFace embeddings
	embeddings = load_embedding()

	# Storing vectors in repo-specific ChromaDB
	vectordb = Chroma.from_documents(text_chunks, embedding=embeddings, persist_directory=db_path)
	vectordb.persist()


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Build vector index for a repository path.")
	parser.add_argument("--repo-path", default="repo", help="Path to the cloned repository.")
	parser.add_argument("--db-path", default="db", help="Path to persist Chroma vector DB.")
	args = parser.parse_args()

	build_index(args.repo_path, args.db_path)
