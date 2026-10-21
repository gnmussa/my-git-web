import os
import requests
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# --- MFUMO WA KULINDA QUOTA (RATE LIMITING) ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Hifadhi funguo salama kutoka kwenye Dashboard ya Render
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

@app.route('/api/scribe', methods=['POST'])
@limiter.limit("5 per minute")
def medical_scribe():
    data = request.get_json()
    if not data or 'prompt' not in data or 'engine' not in data:
        return jsonify({"error": "Data haijakamilika. prompt na engine vinahitajika."}), 400

    prompt_text = data['prompt']
    ai_engine = data['engine'].lower()

    # --- NJIA YA 1: MFUMO WA GEMINI (URL IMEREKEBISHWA) ---
    if ai_engine == 'gemini':
        model_name = "gemini-1.5-flash" 
        # URL SAHIHI YA GEMINI API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            res_data = response.json()
            
            if 'error' in res_data:
                return jsonify({"status": "error", "message": res_data['error']['message']}), 400
                
            ai_result = res_data['candidates'][0]['content']['parts'][0]['text']
            return jsonify({"status": "success", "report": ai_result})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Gemini Error: {str(e)}"}), 500

    # --- NJIA YA 2: MFUMO WA GROQ (URL IMEREKEBISHWA) ---
    elif ai_engine == 'groq':
        model_name = "llama3-8b-8192"
        # URL SAHIHI YA GROQ CHAT COMPLETIONS API
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt_text}]
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            res_data = response.json()
            
            if 'error' in res_data:
                return jsonify({"status": "error", "message": res_data['error']['message']}), 400
                
            ai_result = res_data['choices'][0]['message']['content']
            return jsonify({"status": "success", "report": ai_result})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Groq Error: {str(e)}"}), 500

    else:
        return jsonify({"error": "Engine haitambuliki. Tumia 'gemini' au 'groq'."}), 400

if __name__ == '__main__':
    # Render inahitaji programu isome port inayotolewa na OS mazingira
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
