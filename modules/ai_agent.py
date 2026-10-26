import os
import json
import re
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from modules.rag_snomed import search_medical_term
import streamlit as st

load_dotenv()

def get_llm():
    api_key = st.session_state.get("custom_api_key", "")
    
    if not api_key:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass
            
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")
    
    if not api_key:
        raise ValueError("API Key belum ditemukan! Mohon masukkan API Key di menu Pengaturan sidebar.")
        
    return ChatGoogleGenerativeAI(
        model="gemini-3.8-flash",  
        google_api_key=api_key,
        temperature=0.3,           
        max_output_tokens=600    
    )

def extract_text_from_response(response_content):
    if isinstance(response_content, str):
        return response_content
    if isinstance(response_content, list):
        text_content = ""
        for part in response_content:
            if isinstance(part, dict) and 'text' in part:
                text_content += part['text']
            elif hasattr(part, 'text'):
                text_content += part.text
            elif isinstance(part, str):
                text_content += part
        return text_content
    return str(response_content)

def generate_anamnesis_response(user_input, chat_history):
    # 1. Cari istilah medis terkait di SNOMED CT via ChromaDB yang sudah di-cache
    relevant_docs = search_medical_term(user_input, k=3)
    snomed_context = "\n".join([doc.page_content for doc in relevant_docs]) if relevant_docs else "Tidak ada data spesifik."

    # 2. Prompt ketat agar AI menghasilkan pertanyaan lanjutan secara dinamis
    system_instruction = f"""
Anda adalah Dokter Spesialis Kardiologi dan Expert AI Anamnesis Klinis.
Tugas Anda adalah memandu proses wawancara medis secara progresif dan sistematis.

ATURAN UTAMA:
1. Analisis jawaban user, lalu berikan tanggapan klinis yang interaktif dan terarah.
2. Setiap langkah harus maju ke topik baru (misal: dari Karakteristik Nyeri -> Penjalaran -> Durasi -> Faktor Pemicu -> Gejala Penyerta).
3. Jika informasi gejala sudah cukup terkumpul, berikan kesimpulan diagnosis beserta kode terminologi SNOMED CT yang sesuai.
4. Di bagian akhir, WAJIB berikan tepat 3 rekomendasi pertanyaan lanjutan (Quick Actions) yang BARU, BERBEDA, dan relevan dengan kondisi pasien saat ini dalam format JSON array murni.

Referensi SNOMED CT:
---
{snomed_context}
---

FORMAT OUTPUT WAJIB:
[Tulis analisis/tanggapan medis singkat dan terarah di sini]

===QUICK_ACTIONS===
[
  "Pertanyaan lanjutan baru 1",
  "Pertanyaan lanjutan baru 2",
  "Pertanyaan lanjutan baru 3"
]
"""

    messages = [SystemMessage(content=system_instruction)]
    
    for msg in chat_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
            
    messages.append(HumanMessage(content=user_input))
    
    try:
        # Inisialisasi LLM dengan benar dari fungsi get_llm()
        llm = get_llm()
        response = llm.invoke(messages)
        raw_text = extract_text_from_response(response.content)
    except Exception as e:
        return f"Terjadi kesalahan saat memanggil LLM: {str(e)}", [
            "Bagaimana karakteristik nyeri yang dirasakan?",
            "Kapan pertama kali keluhan ini dirasakan?",
            "Apakah ada riwayat penyakit penyerta?"
        ]
    
    text_response = raw_text
    # Default fallback dinamis jika AI gagal memberikan format JSON
    quick_actions = [
        "Apakah nyeri menjalar ke bagian tubuh lain?",
        "Berapa lama durasi keluhan ini berlangsung?",
        "Apakah ada gejala penyerta seperti sesak napas?"
    ]
    
    if "===QUICK_ACTIONS===" in raw_text:
        parts = raw_text.split("===QUICK_ACTIONS===")
        text_response = parts[0].strip()
        try:
            json_str = parts[1].strip()
            json_str = re.sub(r'```json|```', '', json_str).strip()
            parsed_actions = json.loads(json_str)
            if isinstance(parsed_actions, list) and len(parsed_actions) > 0:
                quick_actions = parsed_actions
        except Exception:
            # Jika parsing gagal, pertahankan hasil teks dari AI tapi biarkan quick actions aman
            pass
            
    return text_response, quick_actions