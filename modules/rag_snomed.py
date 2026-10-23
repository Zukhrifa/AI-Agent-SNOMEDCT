from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

def get_snomed_retriever(k=3):
    """
    Menginisialisasi dan mengembalikan retriever dari ChromaDB lokal
    untuk pencarian istilah medis SNOMED CT.
    """
    # Menggunakan model embedding lokal yang sama saat proses ingest
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    # Memuat database vektor dari folder lokal
    vectorstore = Chroma(
        persist_directory="./chroma_db",
        embedding_function=embeddings
    )
    
    # Mengubah vectorstore menjadi retriever dengan top-k hasil relevan
    retriever = vectorstore.as_retriever(search_kwargs={"k": k})
    return retriever

def search_medical_term(query: str, k=3):
    """
    Fungsi helper untuk mencari terminologi medis berdasarkan input teks bebas.
    """
    retriever = get_snomed_retriever(k=k)
    docs = retriever.invoke(query)
    return docs