import os
import requests
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# Render iko nyuma ya proxy: hii inasoma IP halisi ya mtumiaji kwa ajili ya rate limit
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# --- MFUMO WA KULINDA QUOTA (RATE LIMITING) ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Funguo zinatoka Render Dashboard > Environment
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# Hiari: ukiweka APP_TOKEN kwenye Render, kila ombi lazima litume header X-App-Token
APP_TOKEN = os.environ.get("APP_TOKEN", "")

# Majina ya models (kila engine ina main kisha fallback). Hakikisha yapo kwenye docs za Google na Groq.
GEMINI_MODELS = [
    ("gemini-3.8-flash", "gemini-main"),
    ("gemini-3.7-flash", "gemini-fallback"),
]
GROQ_MODELS = [
    ("openai/gpt-oss-20b", "groq-main"),
    ("groq/compound", "groq-fallback"),
]

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT = 20



SYSTEM_INSTRUCTION = (
    "You are an expert Digital Medical Assistant and accurate Clinical Scribe supporting a doctor.\n"
    "The user message contains a LANGUAGE line followed by patient data. Write the entire response "
    "in Professional Medical English if LANGUAGE is English, or in Professional Medical French if "
    "LANGUAGE is French. Never use any other language.\n\n"
    "RULES:\n"
    "- Use data provided. Do NOT invent symptoms, negatives (e.g. 'no vomiting'), "
    "characteristics, temperatures, vital signs or history. If information is missing, skip it "
    "instead of writing 'not documented'.\n"
    "- Weigh the OBJECTIVE signs at least as heavily as the SUBJECTIVE complaints.\n"
    "- Use precise medical vocabulary suitable for medical professionals. Be concise.\n\n"
    "STRUCTURE: exactly four sections, with these headings in bold:\n"
    "**1. CLINICAL NOTES**\n"
    "**2. DOCTOR'S REMARKS**\n"
    "**3. POSSIBLE INVESTIGATIONS**\n"
    "**4. SUGGESTED TREATMENT / MANAGEMENT PLAN**\n"
    "- Section 1: neutral third-person clinical style (e.g. 'The patient presents with...').\n"
    "- Section 2: first person, as the treating doctor writing in the record ('I suspect...', "
    "'My impression is...', 'I would like to rule out...', 'I recommend...'). Never address the "
    "reader in the second person. Do NOT write 'I examined', 'on my examination I found', "
    "'I asked the patient' or similar unless that information was provided.\n"
    "- Section 4: first list the differential diagnoses in order, each with its ICD-10 code "
    "(format: Diagnosis - Code). After that, give drug doses and regimens in a separate block "
    "headed 'Doses for clinician verification', not mixed with the doctor's remarks.\n"
    "- DOSING RULE: give doses only for conditions reasonably supported by the data. If the data "
    "are insufficient for empirical treatment, recommend investigations first. For children, dose "
    "per kg and state that body weight is required.\n\n"
    "FORMAT: plain text. Use **double asterisks** for headings, simple '-' lists, and no markdown "
    "tables, no # headings and no single-asterisk italics.\n"
    "End with exactly: AI-generated decision support. Must be reviewed by a licensed clinician."
)






def ask_gemini(prompt_text):
    """Jaribu kila model ya Gemini kwa mpangilio. Rudisha (text, label) au (None, None)."""
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    payload = {
    "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
    "contents": [{"parts": [{"text": prompt_text}]}],
    "generationConfig": {"temperature": 0.2}
}

    for model_name, label in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            data = response.json()
            if "error" in data:
                raise Exception(data["error"].get("message", "Hitilafu isiyojulikana"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return text, label
        except Exception as e:
            # Kosa linaonekana kwenye Render > Logs
            print(f"{model_name} failed: {e}", flush=True)

    return None, None


def ask_groq(prompt_text):
    """Jaribu kila model ya Groq kwa mpangilio. Rudisha (text, label) au (None, None)."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}"
    }

    for model_name, label in GROQ_MODELS:
payload = {
    "model": model_name,
    "messages": [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": prompt_text}
    ],
    "temperature": 0.2
}
        try:
            response = requests.post(GROQ_URL, json=payload, headers=headers, timeout=TIMEOUT)
            data = response.json()
            if "error" in data:
                raise Exception(data["error"].get("message", "Hitilafu isiyojulikana"))
            text = data["choices"][0]["message"]["content"]
            return text, label
        except Exception as e:
            print(f"{model_name} failed: {e}", flush=True)

    return None, None


@app.route('/health')
@limiter.exempt
def health():
    return jsonify({"ok": True})


@app.route('/api/scribe', methods=['POST'])
@limiter.limit("5 per minute")
def medical_scribe():
    # Ulinzi wa hiari kwa token
    if APP_TOKEN and request.headers.get("X-App-Token") != APP_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if (not isinstance(data, dict)
            or not isinstance(data.get('prompt'), str)
            or not isinstance(data.get('engine'), str)
            or not data['prompt'].strip()):
        return jsonify({"error": "Data haijakamilika. prompt na engine vinahitajika (maandishi)."}), 400

    prompt_text = data['prompt']
    ai_engine = data['engine'].strip().lower()
 
    if ai_engine == 'gemini':
        result, label = ask_gemini(prompt_text)
        if result is None:
            result, label = ask_groq(prompt_text)
        failed_msg = "Mifumo yote imefeli. Angalia Render Logs."

    elif ai_engine == 'groq':
        result, label = ask_groq(prompt_text)
        failed_msg = "Mifumo yote ya Groq imefeli. Angalia Render Logs."
    else:
        return jsonify({"error": "Engine haitambuliki. Tumia 'gemini' au 'groq'."}), 400

    if result is None:
        return jsonify({"status": "error", "message": failed_msg}), 502

    return jsonify({"status": "success", "engine_used": label, "report": result})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)