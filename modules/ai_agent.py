import os
import json
import re
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from modules.rag_snomed import search_medical_term

load_dotenv()

def get_llm():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY tidak ditemukan di file .env!")
        
    return ChatGoogleGenerativeAI(
        model="gemini-3.8-flash",  # Menggunakan model flash yang lebih stabil dan cepat untuk free tier
        google_api_key=api_key,
        temperature=0.3,
        max_output_tokens=400
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

def generate_anamnesis_response(user_input: str, chat_history: list):
    llm = get_llm()
    
    # RAG pencarian SNOMED CT
    retrieved_docs = search_medical_term(user_input, k=2)
    snomed_context = "\n".join([doc.page_content for doc in retrieved_docs])
    
    # Prompt ketat agar pertanyaan Quick Actions TIDAK BERULANG dan mengerucut ke kode SNOMED CT
    system_instruction = f"""
Anda adalah Dokter Spesialis Kardiologi dan Expert AI Anamnesis Klinis.
Tugas Anda adalah memandu proses wawancara medis secara progresif dan sistematis.

ATURAN UTAMA:
1. JANGAN PERNAH mengulang pertanyaan Quick Actions yang sudah ditanyakan sebelumnya di riwayat chat. Setiap langkah harus maju ke topik baru (misal: dari Karakteristik Nyeri -> Penjalaran -> Durasi -> Faktor Pemicu -> Gejala Penyerta seperti sesak/keringat dingin).
2. Analisis jawaban user, lalu berikan kesimpulan klinis sementara.
3. Jika informasi gejala sudah cukup terkumpul, sebutkan kesimpulan diagnosis beserta kode terminologi SNOMED CT yang paling sesuai dari referensi di bawah.
4. Di bagian akhir, berikan **tepat 3 rekomendasi pertanyaan lanjutan (Quick Actions) yang BARU dan BERBEDA** dalam format JSON array murni.

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
    
    response = llm.invoke(messages)
    raw_text = extract_text_from_response(response.content)
    
    text_response = raw_text
    quick_actions = [
        "Apakah nyeri dada menjalar hingga ke lengan kiri, leher, atau rahang?",
        "Sudah berapa lama durasi serangan nyeri ini berlangsung?",
        "Apakah keluhan disertai keringat dingin, mual, atau sesak napas?"
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
            pass
            
    return text_response, quick_actions