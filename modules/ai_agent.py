import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from modules.rag_snomed import search_medical_term

# Memuat API Key dari berkas .env
load_dotenv()

def get_llm():
    """
    Menginisialisasi model LLM Gemini menggunakan API Key dari .env
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY tidak ditemukan di file .env!")
        
    return ChatGoogleGenerativeAI(
        model="gemini-3.8-flash",
        google_api_key=api_key,
        temperature=0.2
    )

def generate_anamnesis_response(user_input: str, chat_history: list):
    """
    Memproses input pengguna, mengambil konteks SNOMED CT via RAG, 
    dan menghasilkan respon agen dokter/asisten kardiologi.
    """
    llm = get_llm()
    
    # 1. Cari terminologi medis relevan dari ChromaDB via RAG
    retrieved_docs = search_medical_term(user_input, k=3)
    snomed_context = "\n".join([doc.page_content for doc in retrieved_docs])
    
    # 2. System Prompt khusus untuk Anamnesis Kardiologi
    system_instruction = f"""
Anda adalah Asisten Dokter Spesialis Kardiologi berbasis AI yang profesional, empatik, dan presisi. 
Tugas Anda adalah melakukan wawancara medis (anamnesis) kepada pasien yang mengalami keluhan terkait jantung.

Panduan Wawancara:
1. Tanyakan gejala secara bertahap (lokasi nyeri, durasi, faktor pengetus, gejala penyerta seperti sesak/keringat dingin).
2. Gunakan bahasa Indonesia yang santun, empatik, dan mudah dipahami oleh awam.
3. Gunakan referensi SNOMED CT di bawah ini untuk mengidentifikasi kemungkinan terminologi medis secara internal, namun sampaikan penjelasan kepada pasien dengan istilah sederhana.

Referensi Terminologi SNOMED CT Terkait Keluhan:
---
{snomed_context}
---

Catatan: Selalu ingatkan pasien bahwa hasil wawancara ini adalah wawancara awal dan membutuhkan verifikasi dokter spesialis jantung.
"""

    # 3. Menyusun riwayat percakapan untuk dikirim ke LLM
    messages = [SystemMessage(content=system_instruction)]
    
    # Masukkan riwayat percakapan sebelumnya
    for msg in chat_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
            
    # Masukkan input pengguna terbaru
    messages.append(HumanMessage(content=user_input))
    
    # 4. Panggil Gemini LLM
    response = llm.invoke(messages)
    
    # Penanganan parsing konten agar menjadi string bersih
    if isinstance(response.content, list):
        text_content = ""
        for part in response.content:
            if isinstance(part, dict) and 'text' in part:
                text_content += part['text']
            elif hasattr(part, 'text'):
                text_content += part.text
            elif isinstance(part, str):
                text_content += part
        return text_content
    else:
        return str(response.content)

def summarize_anamnesis(chat_history: list):
    """
    Fungsi ringkasan cepat untuk merangkum hasil wawancara anamnesis 
    menjadi laporan medis terstruktur bagi dokter.
    """
    llm = get_llm()
    
    conversation_text = ""
    for msg in chat_history:
        role = "Pasien" if msg["role"] == "user" else "AI"
        conversation_text += f"{role}: {msg['content']}\n"
        
    prompt = f"""
Berdasarkan transkrip anamnesis berikut, buatlah ringkasan rekam medis terstruktur:

Transkrip Percakapan:
{conversation_text}

Format Ringkasan:
- **Keluhan Utama:**
- **Riwayat Penyakit Sekarang (RPS):**
- **Kemungkinan Terminologi Medis Relevan:**
- **Rekomendasi Tindakan Lanjutan:**
"""
    
    response = llm.invoke(prompt)
    
    # Penanganan parsing konten agar menjadi string bersih
    if isinstance(response.content, list):
        text_content = ""
        for part in response.content:
            if isinstance(part, dict) and 'text' in part:
                text_content += part['text']
            elif hasattr(part, 'text'):
                text_content += part.text
            elif isinstance(part, str):
                text_content += part
        return text_content
    else:
        return str(response.content)