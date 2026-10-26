from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import streamlit as st

@st.cache_resource
def get_cached_embeddings():
    """
    Memuat model embedding HuggingFace SEKALI SAJA dan menyimpannya di cache memory.
    Membuat proses pencarian menjadi instan tanpa reload berulang.
    """
    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

@st.cache_resource
def get_cached_vectorstore():
    """
    Memuat koneksi ChromaDB lokal SEKALI SAJA ke dalam cache memory.
    """
    embeddings = get_cached_embeddings()
    return Chroma(
        persist_directory="./chroma_db",
        embedding_function=embeddings
    )

def search_medical_term(query: str, k=3):
    """
    Fungsi helper pencarian terminologi medis yang sekarang sudah ngebut 
    karena menggunakan instance cache global.
    """
    vectorstore = get_cached_vectorstore()
    retriever = vectorstore.as_retriever(search_kwargs={"k": k})
    docs = retriever.invoke(query)
    return docs