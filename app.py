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
    ("gemini-3.7-lite", "gemini-fallback"),
]
GROQ_MODELS = [
    ("openai/gpt-oss-20b", "groq-main"),
    ("groq/compound", "groq-fallback"),
]

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT = 30


def ask_gemini(prompt_text):
    """Jaribu kila model ya Gemini kwa mpangilio. Rudisha (text, label) au (None, None)."""
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

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
            "messages": [{"role": "user", "content": prompt_text}]
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
        failed_msg = "Mifumo yote ya Gemini imefeli. Angalia Render Logs."
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