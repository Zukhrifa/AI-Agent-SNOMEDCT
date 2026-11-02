import streamlit.components.v1 as components

# Skrip ini menyisipkan tombol mikrofon ke dalam kotak st.chat_input (di samping tombol kirim)
# dan mengisi teks hasil ucapan langsung ke kolom pesan, sehingga bisa diedit sebelum dikirim.
_VOICE_HTML = r"""
<script>
(function () {
  var P = window.parent;
  var D = P.document;
  var LANG = "__LANG__";

  var MIC_SVG = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>';

  var CSS = [
    '#st-voice-mic{display:flex;align-items:center;justify-content:center;width:32px;height:32px;',
    'margin-right:4px;border:none;border-radius:8px;background:transparent;color:#64748b;',
    'cursor:pointer;flex-shrink:0;align-self:flex-end;margin-bottom:6px;transition:all .15s;}',
    '#st-voice-mic:hover{background:#eff6ff;color:#2563eb;}',
    '#st-voice-mic.listening{background:#fee2e2;color:#dc2626;animation:stvoicepulse 1.2s infinite;}',
    '#st-voice-mic:disabled{opacity:.4;cursor:not-allowed;}',
    '@keyframes stvoicepulse{0%{box-shadow:0 0 0 0 rgba(220,38,38,.4);}',
    '70%{box-shadow:0 0 0 8px rgba(220,38,38,0);}100%{box-shadow:0 0 0 0 rgba(220,38,38,0);}}'
  ].join('');

  // Sembunyikan wadah iframe ini (tingginya 0) supaya tidak menambah jarak di halaman
  try {
    var fe = window.frameElement;
    if (fe) {
      var box = fe.closest('[data-testid="stElementContainer"]') || fe.closest('.element-container') || fe.parentElement;
      if (box) box.style.display = 'none';
    }
  } catch (e) {}

  // Bersihkan instance lama (Streamlit bisa memuat ulang skrip ini)
  var old = P.__stVoice;
  if (old) {
    try { old.observer.disconnect(); } catch (e) {}
    try { if (old.rec) old.rec.stop(); } catch (e) {}
  }
  var state = { observer: null, rec: null, listening: false };
  P.__stVoice = state;

  var oldStyle = D.getElementById('st-voice-style');
  if (oldStyle) oldStyle.remove();
  var style = D.createElement('style');
  style.id = 'st-voice-style';
  style.textContent = CSS;
  D.head.appendChild(style);

  function getRoot() { return D.querySelector('[data-testid="stChatInput"]'); }
  function getTextarea() {
    var r = getRoot();
    return r ? r.querySelector('textarea') : null;
  }

  // Isi textarea dengan cara yang dikenali React (Streamlit)
  function setValue(ta, text) {
    var setter = Object.getOwnPropertyDescriptor(P.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, text);
    ta.dispatchEvent(new P.Event('input', { bubbles: true }));
  }

  function setUi(on) {
    var mic = D.getElementById('st-voice-mic');
    if (!mic) return;
    if (on) mic.classList.add('listening'); else mic.classList.remove('listening');
    mic.title = on ? 'Klik untuk berhenti merekam' : 'Voice typing (Bahasa Indonesia)';
  }

  function toggle() {
    var ta = getTextarea();
    if (!ta || ta.disabled) return;

    if (state.listening && state.rec) {
      try { state.rec.stop(); } catch (e) {}
      return;
    }

    var SR = P.SpeechRecognition || P.webkitSpeechRecognition;
    if (!SR) {
      P.alert('Browser Anda tidak mendukung Web Speech API. Gunakan Google Chrome atau Microsoft Edge.');
      return;
    }

    var rec = new SR();
    rec.lang = LANG;
    rec.continuous = true;
    rec.interimResults = true;

    var base = (ta.value || '').replace(/\s+$/, '');
    var finalText = '';

    function render(interim) {
      var cur = getTextarea();
      if (!cur) return;
      var spoken = finalText;
      var tail = interim.trim();
      if (tail) spoken = spoken ? spoken + ' ' + tail : tail;
      var text = base ? (spoken ? base + ' ' + spoken : base) : spoken;
      setValue(cur, text);
    }

    rec.onstart = function () { state.listening = true; setUi(true); };

    rec.onresult = function (ev) {
      var interim = '';
      for (var i = ev.resultIndex; i < ev.results.length; i++) {
        var r = ev.results[i];
        if (r.isFinal) {
          var piece = r[0].transcript.trim();
          if (piece) finalText += (finalText ? ' ' : '') + piece;
        } else {
          interim += r[0].transcript;
        }
      }
      render(interim);
    };

    rec.onerror = function (ev) {
      if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
        P.alert('Izin mikrofon ditolak. Klik ikon gembok di address bar, izinkan Microphone, lalu coba lagi.');
      } else if (ev.error === 'network') {
        P.alert('Voice typing membutuhkan koneksi internet (layanan pengenalan suara Chrome/Edge).');
      } else if (ev.error === 'audio-capture') {
        P.alert('Mikrofon tidak terdeteksi.');
      }
    };

    rec.onend = function () {
      state.listening = false;
      setUi(false);
      var cur = getTextarea();
      if (cur) {
        cur.focus();
        var n = cur.value.length;
        try { cur.setSelectionRange(n, n); } catch (e) {}
      }
    };

    state.rec = rec;
    try { rec.start(); } catch (e) {}
  }

  // Sisipkan tombol mic tepat sebelum tombol kirim; dipanggil ulang jika React me-render ulang
  function ensure() {
    var root = getRoot();
    if (!root) return;
    var ta = root.querySelector('textarea');
    var submit = root.querySelector('button[data-testid="stChatInputSubmitButton"]') ||
                 root.querySelector('button:not(#st-voice-mic)');
    if (!ta || !submit) return;

    // Jika tombol kirim dibungkus wadah sendiri, sisipkan mic di luar wadah itu
    var anchor = submit;
    var p = submit.parentElement;
    if (p && p !== root && p.children.length === 1 && p.parentElement && p.parentElement.contains(ta)) {
      anchor = p;
    }

    var mic = D.getElementById('st-voice-mic');
    if (mic && mic.nextElementSibling === anchor) {
      mic.disabled = !!ta.disabled;
      return;
    }
    if (mic) mic.remove();

    mic = D.createElement('button');
    mic.id = 'st-voice-mic';
    mic.type = 'button';
    mic.innerHTML = MIC_SVG;
    mic.disabled = !!ta.disabled;
    mic.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggle();
    });
    anchor.parentElement.insertBefore(mic, anchor);
    setUi(state.listening);
  }

  var scheduled = false;
  state.observer = new P.MutationObserver(function () {
    if (scheduled) return;
    scheduled = true;
    P.requestAnimationFrame(function () {
      scheduled = false;
      ensure();
    });
  });
  state.observer.observe(D.body, { childList: true, subtree: true });
  ensure();
})();
</script>
"""


def render_voice_button(lang: str = "id-ID") -> None:
    """Pasang tombol mikrofon di dalam kotak pesan (st.chat_input)."""
    components.html(_VOICE_HTML.replace("__LANG__", lang), height=0)