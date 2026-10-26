import streamlit as st
import streamlit.components.v1 as components
from modules.ai_agent import generate_anamnesis_response

def render_chat_room():
    patient = st.session_state.active_patient
    
    # Inisialisasi riwayat pesan jika belum ada
    if "messages" not in st.session_state:
        st.session_state.messages = patient.get("messages", [])

    # Header Pasien
    st.markdown(f"""
        <div style="padding: 12px 0; border-bottom: 1px solid #e2e8f0; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between;">
            <div>
                <span style="font-size: 18px; font-weight: 700; color: #0f172a;">{patient['name']}</span>
                <span style="font-size: 13px; color: #64748b; margin-left: 10px;">{patient['mrn']}</span>
                <span style="background-color: #dcfce7; color: #166534; font-size: 11px; padding: 2px 8px; border-radius: 12px; margin-left: 8px; font-weight: 600;">Active</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # --- RENDER RIWAYAT PERCAKAPAN (BUBBLE CHAT) ---
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            # Bubble User di Sisi Kanan (Biru)
            st.markdown(f"""
                <div style="display: flex; justify-content: flex-end; margin-bottom: 16px;">
                    <div style="background-color: #2563eb; color: white; padding: 14px 18px; border-radius: 18px 18px 2px 18px; max-width: 80%; font-size: 14px; line-height: 1.5; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                        {msg['content']}
                    </div>
                </div>
            """, unsafe_allow_html=True)
        else:
            # Bubble AI Agent di Sisi Kiri
            st.markdown(f"""
                <div style="display: flex; align-items: flex-start; margin-bottom: 16px;">
                    <div style="width: 32px; height: 32px; background-color: #eff6ff; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 10px; color: #2563eb; font-weight: bold; font-size: 14px; flex-shrink: 0;">
                        🤖
                    </div>
                    <div style="flex: 1;">
                        <div style="font-size: 13px; font-weight: 600; color: #16a34a; margin-bottom: 4px;">AI Agent</div>
                        <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; max-width: 85%; font-size: 14px; color: #334155; line-height: 1.5; box-shadow: 0 1px 2px rgba(0,0,0,0.02);">
                            <div style="font-weight: 600; color: #0f172a; margin-bottom: 6px;">Assessment</div>
                            {msg['content']}
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

    # Rekomendasi Quick Actions
    if st.session_state.get("quick_actions"):
        st.markdown("<div style='margin-top: 10px; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: #64748b;'>Suggested Clinical Actions:</div>", unsafe_allow_html=True)
        for idx, action_text in enumerate(st.session_state.quick_actions[:3]):
            col_num, col_btn = st.columns([1, 11])
            with col_num:
                st.markdown(f"""
                    <div style="background-color: #eff6ff; color: #2563eb; font-weight: 700; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                        {idx + 1}
                    </div>
                """, unsafe_allow_html=True)
            with col_btn:
                if st.button(action_text, key=f"qa_btn_{idx}", use_container_width=True):
                    send_user_message(action_text)
                    st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # --- WIDGET VOICE TYPING SISTEM (WEB SPEECH API) ---
    # Memungkinkan Anda mendikte suara ke teks bahasa Indonesia secara kumulatif
    voice_typing_widget = """
    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
        <button id="micBtn" onclick="toggleVoiceTyping()" style="background-color: #ffffff; border: 1px solid #cbd5e1; color: #334155; padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 13px; display: flex; align-items: center; gap: 6px; font-weight: 500; box-shadow: 0 1px 2px rgba(0,0,0,0.02);">
            🎙️ <span id="micText">Voice Typing (Bahasa Indonesia)</span>
        </button>
        <span id="speechStatus" style="font-size: 12px; color: #64748b; font-style: italic;"></span>
    </div>

    <script>
        let recognition;
        let isListening = false;

        function toggleVoiceTyping() {
            const micBtn = document.getElementById('micBtn');
            const micText = document.getElementById('micText');
            const status = document.getElementById('speechStatus');

            if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
                alert("Browser Anda tidak mendukung Web Speech API. Harap gunakan Google Chrome.");
                return;
            }

            if (!isListening) {
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition = new SpeechRecognition();
                recognition.lang = 'id-ID'; // Bahasa Indonesia
                recognition.interimResults = true;
                recognition.continuous = true;

                recognition.onstart = function() {
                    isListening = true;
                    micBtn.style.backgroundColor = "#fee2e2";
                    micBtn.style.borderColor = "#ef4444";
                    micText.style.color = "#dc2626";
                    micText.innerText = "Mendengarkan...";
                };

                recognition.onresult = function(event) {
                    let finalTranscript = '';
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i].isFinal) {
                            finalTranscript += event.results[i][0].transcript;
                        }
                    }
                    if (finalTranscript !== '') {
                        status.innerText = "Teks terekam: " + finalTranscript;
                        // Kirim otomatis teks hasil suara ke parameter Streamlit untuk diproses
                        window.parent.location.search = "?voice_msg=" + encodeURIComponent(finalTranscript);
                    }
                };

                recognition.onerror = function(event) {
                    status.innerText = "Error: " + event.error;
                };

                recognition.onend = function() {
                    isListening = false;
                    micBtn.style.backgroundColor = "#ffffff";
                    micBtn.style.borderColor = "#cbd5e1";
                    micText.style.color = "#334155";
                    micText.innerText = "Voice Typing (Bahasa Indonesia)";
                };

                recognition.start();
            } else {
                recognition.stop();
            }
        }
    </script>
    """
    components.html(voice_typing_widget, height=40)

    # Tangkap hasil kiriman dari Voice Typing
    if "voice_msg" in st.query_params:
        voice_text = st.query_params["voice_msg"]
        st.query_params.clear()
        send_user_message(voice_text)
        st.rerun()

    # --- KOTAK INPUT UTAMA (STREAMLIT CHAT INPUT) ---
    # Dijamin 100% stabil, tombol kirim & Enter berfungsi sempurna, masuk ke bubble kanan
    user_input = st.chat_input("Type your message...")
    if user_input:
        send_user_message(user_input)
        st.rerun()

def send_user_message(text):
    # Simpan pesan user ke riwayat sesi dan tampil di bubble kanan
    st.session_state.messages.append({"role": "user", "content": text})
    
    with st.spinner("AI sedang menganalisis anamnesis..."):
        ai_reply, next_actions = generate_anamnesis_response(
            text, 
            st.session_state.messages[:-1]
        )
        
    # Simpan balasan AI dan tampil di bubble kiri
    st.session_state.messages.append({"role": "assistant", "content": ai_reply})
    st.session_state.quick_actions = next_actions
    
    # Sinkronisasi ke data pasien agar riwayat tersimpan permanen di sidebar
    if st.session_state.active_patient:
        st.session_state.active_patient["messages"] = st.session_state.messages
        st.session_state.active_patient["last_msg"] = text
        st.session_state.active_patient["quick_actions"] = next_actions