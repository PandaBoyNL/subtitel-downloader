from flask import Flask, render_template, request, Response, jsonify
import subprocess
import os
import signal
import threading
import time
from datetime import datetime
import urllib.request
import json

app = Flask(__name__)
current_process = None
LOG_FILE = "/app/process.log"

# De Webhook speciaal voor de contact-knop!
CONTACT_WEBHOOK = "https://discord.com/api/webhooks/1554689555892801687/0a5MfgvjlI9xmY7ZHPGRT-g6WVutdpqvbH5FpaXHgNcetfWRpq-0gKdHkIwkhjmjBH3j"

def get_timestamp():
    return datetime.now().strftime("[%d-%m-%Y %H:%M:%S] ")

def get_texts(lang):
    is_nl = 'nl' in lang.lower()
    return {
        'title': 'SUB-GONE: Ingebakken Ondertiteling Verwijderen' if is_nl else 'SUB-GONE: Remove Hardcoded Subtitles',
        'desc': 'Vul de map in (bijv. 📁 /media) om te scannen en strippen ✨:' if is_nl else 'Enter the folder (e.g. 📁 /media) to scan and strip ✨:',
        'start': '▶️ Start Proces' if is_nl else '▶️ Start Process',
        'stop': '⏹️ Stop Proces' if is_nl else '⏹️ Stop Process',
        'live': '📺 Live Output:' if is_nl else '📺 Live Output:',
        'wait': '⏳ Wachten op actie...' if is_nl else '⏳ Waiting for action...',
        'starting': '🚀 Bezig met starten...' if is_nl else '🚀 Starting...',
        'stopped': '🛑 [INFO] Proces handmatig gestopt.' if is_nl else '🛑 [INFO] Process stopped manually.',
        'err': '⚠️ [FOUT] Live-stream verbroken. Ververs pagina.' if is_nl else '⚠️️ [ERROR] Live-stream lost. Refresh page.',
        'recon': '🔄 Bezig met opnieuw verbinden...' if is_nl else '🔄 Reconnecting...',
        'hist': '📜 Laatste geschiedenis ophalen...' if is_nl else '📜 Fetching history...',
        
        # Vertalingen voor het contactformulier
        'contact_btn': '📩 Contact opnemen' if is_nl else '📩 Contact Creator',
        'contact_title': 'Stuur een bericht naar PandaBoyNL' if is_nl else 'Send a message to PandaBoyNL',
        'contact_sender': 'Jouw naam / Discord / E-mail' if is_nl else 'Your name / Discord / Email',
        'contact_msg': 'Typ hier je vraag, idee of foutmelding...' if is_nl else 'Type your question, idea or bug report...',
        'contact_send': '🚀 Versturen' if is_nl else '🚀 Send',
        'contact_cancel': '❌ Annuleren' if is_nl else '❌ Cancel',
        'contact_success': '✅ Je bericht is succesvol verzonden!' if is_nl else '✅ Message sent successfully!',
        'contact_error': '⚠️ Fout bij verzenden.' if is_nl else '⚠️ Error sending message.'
    }

def background_task(folder, lang):
    global current_process
    env = os.environ.copy()
    env['LANG'] = lang 
    
    current_process = subprocess.Popen(
        ['/app/remove_subs.sh', folder],
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        env=env
    )
    current_process.wait()
    current_process = None

@app.route('/')
def index():
    browser_lang = request.accept_languages.best_match(['nl', 'en']) or 'en'
    t = get_texts(browser_lang)
    return render_template('index.html', t=t, lang=browser_lang)

@app.route('/start', methods=['POST'])
def start_process():
    global current_process
    if current_process is None:
        folder = request.form.get('folder', '/media')
        lang = request.form.get('lang', 'en')
        t = get_texts(lang)
        with open(LOG_FILE, "w") as f:
            f.write(get_timestamp() + t['starting'] + "\n")
        thread = threading.Thread(target=background_task, args=(folder, lang))
        thread.start()
    return jsonify({"status": "success"})

@app.route('/stream')
def stream_logs():
    def generate():
        if not os.path.exists(LOG_FILE):
            yield "⏳ Waiting for action...\n"
            return
        with open(LOG_FILE, "r") as f:
            while True:
                line = f.readline()
                if not line:
                    if current_process is None:
                        break
                    time.sleep(0.5)
                else:
                    yield line
    return Response(generate(), mimetype='text/plain')

@app.route('/status')
def status():
    return jsonify({"running": current_process is not None})

@app.route('/stop', methods=['POST'])
def stop_process():
    global current_process
    lang = request.form.get('lang', 'en')
    t = get_texts(lang)
    if current_process:
        try:
            os.killpg(os.getpgid(current_process.pid), signal.SIGTERM)
            current_process = None
            with open(LOG_FILE, "a") as f:
                f.write("\n" + get_timestamp() + t['stopped'] + "\n")
            return jsonify({"status": "succes"})
        except Exception as e:
            return jsonify({"status": "fout", "message": str(e)})
    return jsonify({"status": "geen proces"})

@app.route('/contact', methods=['POST'])
def handle_contact():
    message = request.form.get('message', '').strip()
    sender = request.form.get('sender', '').strip() or 'Anoniem'
    
    if not message:
        return jsonify({"status": "error"})
        
    # Bouw het Discord bericht op
    content = f"📩 **Nieuw bericht via SUB-GONE WebGUI**\n**Van:** `{sender}`\n**Bericht:**\n```\n{message}\n```"
    data = json.dumps({"content": content}).encode('utf-8')
    req = urllib.request.Request(CONTACT_WEBHOOK, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'SUB-GONE'})
    
    try:
        urllib.request.urlopen(req)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
