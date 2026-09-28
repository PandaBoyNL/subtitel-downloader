import os, random, requests, re, subprocess, struct, time, threading
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

MEDIA_DIR = os.environ.get('MEDIA_DIR', '/media')
API_KEYS = [k.strip() for k in os.environ.get('OS_API_KEYS', '').split(',') if k.strip()]
OS_USER = os.environ.get('OS_USERNAME', '')
OS_PASS = os.environ.get('OS_PASSWORD', '')
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')

AUTHOR_WEBHOOK = "https://discord.com/api/webhooks/..." # (Vul hier je eigen webhook in)

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "UnraidSubDownloader v1.0"

batch_logs = []
is_batch_running = False

def log_msg(msg, msg_type='info'):
    global batch_logs
    t = time.strftime('%H:%M:%S')
    batch_logs.append({"time": t, "msg": msg, "type": msg_type})
    if len(batch_logs) > 500: batch_logs.pop(0)

def hashFile(name):
    try:
        longlongformat = '<q'
        bytesize = struct.calcsize(longlongformat)
        f = open(name, "rb")
        filesize = os.path.getsize(name)
        hash = filesize
        if filesize < 65536 * 2: return None
        for x in range(65536//bytesize):
            buffer = f.read(bytesize)
            (l_value,)= struct.unpack(longlongformat, buffer)
            hash += l_value
            hash = hash & 0xFFFFFFFFFFFFFFFF
        f.seek(max(0,filesize-65536),0)
        for x in range(65536//bytesize):
            buffer = f.read(bytesize)
            (l_value,)= struct.unpack(longlongformat, buffer)
            hash += l_value
            hash = hash & 0xFFFFFFFFFFFFFFFF
        f.close()
        return "%016x" % hash
    except: return None

def clean_query(name):
    if '.' in name and name.rsplit('.', 1)[-1].lower() in ['mkv', 'mp4', 'avi', 'srt']: name = name.rsplit('.', 1)[0]
    words = ['extended edition', 'directors cut', "director's cut", 'unrated', 'special edition', 'theatrical cut', 'remastered', '1080p', '720p', '2160p', '4k', '8k', 'bluray', 'web-dl', 'webrip', 'hdtv', 'x264', 'x265', 'hevc', 'remux', 'aac', 'dts', 'ac3']
    for w in words: name = re.sub(rf'(?i)\b{w}\b', ' ', name)
    season, episode, year = "", "", ""
    match_se = re.search(r'(?i)s(\d{1,2})e(\d{1,2})', name)
    if match_se:
        season = int(match_se.group(1))
        episode = int(match_se.group(2))
        name = name[:match_se.start()]
    paren_years = list(re.finditer(r'\((19\d{2}|20\d{2})\)', name))
    years = list(re.finditer(r'\b(19\d{2}|20\d{2})\b', name))
    if paren_years:
        match_year = paren_years[-1]
        year = match_year.group(1)
        name = name[:match_year.start()]
    elif years:
        match_year = years[-1]
        year = match_year.group(1)
        name = name[:match_year.start()]
    name = re.sub(r'[-_\[\]\.\(\)]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip(), year, season, episode

def get_best_search_terms(fullpath):
    fullpath = fullpath.replace('\\', '/')
    path_parts = [p for p in fullpath.split('/') if p]
    if not path_parts: return "", "", "", ""
    filename = path_parts[-1]
    folder_name = path_parts[-2] if len(path_parts) > 1 else ""
    grandparent = path_parts[-3] if len(path_parts) > 2 else ""
    f_title, f_year, f_season, f_ep = clean_query(filename)
    d_title, d_year, d_season, d_ep = clean_query(folder_name)
    season = f_season or d_season
    episode = f_ep or d_ep
    year = d_year or f_year
    title = f_title
    if d_year and not season: title = d_title
    if season and episode:
        if len(f_title.replace(' ', '')) < 3:
            if 'season' in d_title.lower() or 'seizoen' in d_title.lower() or re.match(r'^s\d+$', d_title.lower()):
                gp_title, _, _, _ = clean_query(grandparent)
                title = gp_title
            else: title = d_title
    if not title: title = d_title or filename.rsplit('.', 1)[0]
    return title, year, season, episode

# --- NIEUW: Controleer of ondertiteling al bestaat (extern of ingebakken) ---
def has_existing_subtitle(video_path, lang):
    base_path = os.path.splitext(video_path)[0]
    
    # 1. Controleer op losse SRT bestanden naast de video
    possible_srts = [f"{base_path}.srt", f"{base_path}.{lang}.srt"]
    if lang == 'nl':
        possible_srts.extend([f"{base_path}.nld.srt", f"{base_path}.dut.srt", f"{base_path}.dutch.srt"])
    elif lang == 'en':
        possible_srts.extend([f"{base_path}.eng.srt", f"{base_path}.english.srt"])
        
    for srt in possible_srts:
        if os.path.exists(srt):
            return True, f"Extern SRT-bestand gevonden"
            
    # 2. Controleer op ingebakken streams via ffprobe
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "s",
            "-show_entries", "stream_tags=language",
            "-of", "csv=p=0",
            video_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if result.stdout:
            langs = [line.strip().lower() for line in result.stdout.split('\n') if line.strip()]
            search_langs = [lang.lower()]
            if lang == 'nl':
                search_langs.extend(['nld', 'dut', 'dutch'])
            elif lang == 'en':
                search_langs.extend(['eng', 'english'])
                
            for l in langs:
                if l in search_langs:
                    return True, f"Ingebakken '{l.upper()}' track gevonden"
    except Exception:
        pass # ffprobe fout of niet aanwezig, we negeren het veilig
        
    return False, ""

def send_discord_alert(title, description, color):
    if not DISCORD_WEBHOOK: return
    embed = {"title": title, "description": description, "color": color}
    try: requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]})
    except: pass

# Discord Webhook geüpdatet met "Overgeslagen" lijst!
def send_discord_webhook(success_list, failed_list, skipped_list=None):
    if not DISCORD_WEBHOOK: return
    if skipped_list is None: skipped_list = []
    
    embed = {"title": "🎬 Subtitel downloader: Batch Voltooid!", "color": 3066993 if len(failed_list) == 0 else 15158332, "fields": []}
    
    if success_list:
        val = "\n".join(success_list)
        if len(val) > 1000: val = val[:950] + "\n...(Lijst ingekort)"
        embed["fields"].append({"name": f"✅ Succesvol ({len(success_list)})", "value": val})
        
    if skipped_list:
        val = "\n".join(skipped_list)
        if len(val) > 1000: val = val[:950] + "\n...(Lijst ingekort)"
        embed["fields"].append({"name": f"⏭️ Overgeslagen (Al aanwezig) ({len(skipped_list)})", "value": val})
        
    if failed_list:
        val = "\n".join(failed_list)
        if len(val) > 1000: val = val[:950] + "\n...(Lijst ingekort)"
        embed["fields"].append({"name": f"❌ Mislukt ({len(failed_list)})", "value": val})
        
    if not success_list and not failed_list and not skipped_list: 
        embed["description"] = "Niets verwerkt."
        
    try: requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]})
    except: pass

def internal_search(fullpath, lang):
    title, year, season, episode = get_best_search_terms(fullpath)
    abs_path = os.path.abspath(os.path.join(MEDIA_DIR, fullpath))
    file_hash = hashFile(abs_path) if os.path.exists(abs_path) else None
    
    def fetch_and_filter(prms, check_strict=True):
        valid = []
        all_keys_rate_limited = True
        
        for api_key in API_KEYS:
            headers = {"Api-Key": api_key, "User-Agent": USER_AGENT, "Accept": "application/json"}
            try:
                r = requests.get(f"{API_BASE}/subtitles", headers=headers, params=prms)
                if r.status_code == 429: continue
                    
                all_keys_rate_limited = False
                raw_subs = r.json().get('data', []) if r.status_code == 200 else []
                
                for sub in raw_subs:
                    a = sub.get('attributes', {})
                    release = str(a.get('release', '')).lower()
                    feature = a.get('feature_details') or {}
                    m_name = str(feature.get('movie_name', '')).lower()
                    t_name = str(feature.get('title', '')).lower()
                    
                    score = int(a.get('download_count') or 0) + (float(a.get('ratings') or 0) * 1000)
                    t_lower = title.lower()
                    
                    release_clean = re.sub(r'[^a-z0-9]', ' ', release)
                    m_name_clean = re.sub(r'[^a-z0-9]', ' ', m_name)
                    t_name_clean = re.sub(r'[^a-z0-9]', ' ', t_name)
                    t_clean = re.sub(r'[^a-z0-9]', ' ', t_lower)
                    
                    if check_strict:
                        target_words = [w for w in t_clean.split() if w not in ['the', 'and', 'a', 'an', 'of', 'in', 'on', 'de', 'het', 'een'] and len(w) > 0]
                        if not target_words: target_words = [w for w in t_clean.split() if len(w) > 0]
                        pattern_ordered = r'.*?'.join([rf'\b{re.escape(w)}\b' for w in target_words])
                        match_release = bool(re.search(pattern_ordered, release_clean))
                        match_mname = all(re.search(rf'\b{re.escape(w)}\b', m_name_clean) for w in target_words) if m_name_clean else False
                        match_tname = all(re.search(rf'\b{re.escape(w)}\b', t_name_clean) for w in target_words) if t_name_clean else False
                        if not (match_release or match_mname or match_tname): continue
                    
                    if t_lower == m_name or t_lower == t_name: score += 100000000
                    elif m_name and (t_clean in m_name_clean or m_name_clean in t_clean): score += 50000000
                    if year:
                        if str(year) == str(feature.get('year', '')): score += 10000000
                        elif re.search(rf'\b{year}\b', release_clean): score += 5000000
                    if 'web' in release_clean or 'bluray' in release_clean: score += 50000
                    sub['sort_score'] = score
                    valid.append(sub)
                
                break 
            except: continue
                
        if all_keys_rate_limited: return [], True
        valid.sort(key=lambda x: x['sort_score'], reverse=True)
        return valid, False

    try:
        subs, search_term_display = [], ""
        if file_hash:
            search_term_display = f"Hash: {file_hash}"
            subs, is_limited = fetch_and_filter({"moviehash": file_hash, "languages": lang}, check_strict=False)
            if is_limited: return True, search_term_display, [], "API limiet bereikt op alle keys"
            
        if not subs:
            search_term_display = f"Titel: '{title}' | Jaar: '{year}'"
            p3 = {"query": title, "languages": lang}
            if year: p3["year"] = year
            if season: p3["season_number"] = season
            if episode: p3["episode_number"] = episode
            subs, is_limited = fetch_and_filter(p3, check_strict=True)
            if is_limited: return True, search_term_display, [], "API limiet bereikt op alle keys"
            
        if not subs and year:
            search_term_display = f"Titel: '{title} {year}'"
            p3b = {"query": f"{title} {year}", "languages": lang}
            if season: p3b["season_number"] = season
            if episode: p3b["episode_number"] = episode
            subs, is_limited = fetch_and_filter(p3b, check_strict=True)
            if is_limited: return True, search_term_display, [], "API limiet bereikt op alle keys"
            
        if not subs and year:
            search_term_display = f"Titel: '{title}' (Zonder Jaar)"
            p4 = {"query": title, "languages": lang}
            if season: p4["season_number"] = season
            if episode: p4["episode_number"] = episode
            subs, is_limited = fetch_and_filter(p4, check_strict=True)
            if is_limited: return True, search_term_display, [], "API limiet bereikt op alle keys"
            
        return False, search_term_display, subs, ""
    except Exception as e: return False, "", [], str(e)

def internal_download(file_id, video_path, lang):
    for api_key in API_KEYS:
        payload = {"username": OS_USER, "password": OS_PASS}
        headers = {"Api-Key": api_key, "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
        try:
            login_r = requests.post(f"{API_BASE}/login", json=payload, headers=headers)
            if login_r.status_code != 200: continue
            
            token = login_r.json().get('token')
            dl_headers = {"Api-Key": api_key, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
            dl_r = requests.post(f"{API_BASE}/download", headers=dl_headers, json={"file_id": int(file_id)})
            
            if dl_r.status_code == 429 or 'limit' in dl_r.text.lower(): continue
                
            if dl_r.status_code == 200:
                link = dl_r.json().get('link')
                srt_data = requests.get(link, headers={"User-Agent": USER_AGENT})
                if len(srt_data.content) < 50 or b'<html' in srt_data.content.lower():
                    return False, False, "", "Corrupt file from OpenSubtitles."
                
                abs_video_path = os.path.join(MEDIA_DIR, video_path)
                srt_path = f"{os.path.splitext(abs_video_path)[0]}.{lang}.srt"
                with open(srt_path, 'wb') as f: f.write(srt_data.content)
                try:
                    subprocess.run(["ffs", abs_video_path, "-i", srt_path, "-o", srt_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    msg = "✅ Perfect synchroon!"
                except: msg = "⚠️ Originele timing behouden."
                
                return True, False, srt_path, msg
        except: continue
    return False, True, "", "Download limiet bereikt op ALLE API keys."

def background_batch_processor(paths, lang):
    global is_batch_running
    is_batch_running = True
    batch_logs.clear()
    log_msg("🚀 Achtergrond-Batch is gestart! Bestanden scannen...", "info")
    
    found_files = []
    for p in paths:
        full_path = os.path.abspath(os.path.join(MEDIA_DIR, p))
        if not full_path.startswith(os.path.abspath(MEDIA_DIR)): continue
        if os.path.isfile(full_path) and full_path.lower().endswith(('.mkv', '.mp4', '.avi')):
            fname = os.path.basename(full_path)
            if not fname.startswith('.') and 'sample' not in fname.lower():
                found_files.append({"name": fname, "path": os.path.relpath(full_path, MEDIA_DIR)})
        elif os.path.isdir(full_path):
            for root, dirs, files in os.walk(full_path):
                for file in files:
                    if file.lower().endswith(('.mkv', '.mp4', '.avi')):
                        if not file.startswith('.') and 'sample' not in file.lower():
                            fp = os.path.join(root, file)
                            found_files.append({"name": file, "path": os.path.relpath(fp, MEDIA_DIR)})
    
    log_msg(f"✅ Gevonden: {len(found_files)} video's om te verwerken.", "success")
    success_list = []
    failed_list = []
    skipped_list = [] # Nieuwe lijst voor de overgeslagen bestanden
    
    is_paused_state = False 
    
    for item in found_files:
        fullpath = item['path']
        filename = item['name']
        abs_path = os.path.abspath(os.path.join(MEDIA_DIR, fullpath))
        
        # --- PRE-CHECK: Heeft hij al ondertiteling? ---
        exists, reason = has_existing_subtitle(abs_path, lang)
        if exists:
            log_msg(f"⏭️ Overslaan: {filename} ({reason})", "info")
            skipped_list.append(filename)
            continue
            
        log_msg(f"🎬 Starten met: {filename}", "info")
        
        while True: 
            is_rate_limited, search_term, subs, err = internal_search(fullpath, lang)
            
            if is_rate_limited:
                if not is_paused_state:
                    msg = "⏳ API Zoek-limiet bereikt op ALLE sleutels! Automatische pauze van 15 minuten gestart..."
                    log_msg(msg, "warn")
                    send_discord_alert("⚠️ API Limiet Bereikt", msg, 16753920) 
                    is_paused_state = True
                else: log_msg("⏳ Nog steeds gelimiteerd. Opnieuw 15 minuten wachten...", "warn")
                
                time.sleep(900) 
                continue 
                
            if is_paused_state:
                msg = "▶️ API is weer beschikbaar! Zoeken & Downloaden wordt hervat."
                log_msg(msg, "success")
                send_discord_alert("✅ API Hervat", msg, 3066993) 
                is_paused_state = False
                
            if not subs:
                log_msg(f"❌ Niet gevonden: {filename}", "error")
                failed_list.append(f"{filename} (Niet gevonden)")
                break
                
            downloaded = False
            rate_limited_dl = False
            
            for sub in subs[:5]:
                file_id = sub['attributes']['files'][0]['file_id']
                dl_success, dl_limit, path, msg = internal_download(file_id, fullpath, lang)
                
                if dl_limit:
                    rate_limited_dl = True
                    break 
                    
                if dl_success:
                    log_msg(f"✅ Download succes! {msg}", "success")
                    success_list.append(filename)
                    downloaded = True
                    break
                    
            if rate_limited_dl:
                if not is_paused_state:
                    msg = "⏳ API Download-limiet bereikt op ALLE sleutels! Automatische pauze van 15 minuten gestart..."
                    log_msg(msg, "warn")
                    send_discord_alert("⚠️ Download Limiet", msg, 16753920)
                    is_paused_state = True
                else: log_msg("⏳ Download limiet nog steeds actief. Opnieuw 15 minuten wachten...", "warn")
                    
                time.sleep(900) 
                continue 
                
            if is_paused_state:
                msg = "▶️ Download limiet is gereset! Batch wordt hervat."
                log_msg(msg, "success")
                send_discord_alert("✅ Downloads Hervat", msg, 3066993)
                is_paused_state = False
                
            if not downloaded:
                log_msg(f"❌ Download Mislukt: {filename}", "error")
                failed_list.append(f"{filename} (Mislukt)")
                
            break
            
    log_msg("🎉 Achtergrond-Batch is volledig afgerond! Rapport verstuurd naar Discord.", "success")
    send_discord_webhook(success_list, failed_list, skipped_list) # Stuur de overgeslagen lijst mee
    is_batch_running = False

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/languages')
def get_languages():
    try:
        r = requests.get(f"{API_BASE}/infos/languages", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        return jsonify(r.json())
    except: return jsonify({"data": []})

@app.route('/api/browse')
def browse():
    sub_path = request.args.get('path', '')
    target_path = os.path.abspath(os.path.join(MEDIA_DIR, sub_path))
    if not target_path.startswith(os.path.abspath(MEDIA_DIR)): return jsonify({"error": "Toegang geweigerd"}), 403
    items = []
    if os.path.exists(target_path):
        for entry in sorted(os.listdir(target_path)):
            f = os.path.join(target_path, entry)
            if os.path.isdir(f): items.append({"name": entry, "is_dir": True, "path": os.path.relpath(f, MEDIA_DIR)})
            elif entry.lower().endswith(('.mkv', '.mp4', '.avi')):
                if not entry.startswith('.') and 'sample' not in entry.lower():
                    items.append({"name": entry, "is_dir": False, "path": os.path.relpath(f, MEDIA_DIR)})
    return jsonify({"current_path": sub_path, "items": items})

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json
    fullpath = data.get('fullpath', data.get('filename'))
    lang = data.get('language', 'nl')
    is_limit, search_term, subs, err = internal_search(fullpath, lang)
    if is_limit: return jsonify({"success": False, "rate_limited": True, "error": "API limiet bereikt op alle keys!"})
    if err: return jsonify({"success": False, "search_term": search_term, "error": err})
    return jsonify({"success": True, "search_term": search_term, "data": subs})

@app.route('/api/download', methods=['POST'])
def download():
    data = request.json
    success, is_limit, path, msg = internal_download(data.get('file_id'), data.get('video_path'), data.get('language', 'nl'))
    if is_limit: return jsonify({"rate_limited": True, "error": "Download limiet bereikt op alle keys."}), 429
    if not success: return jsonify({"error": msg}), 500
    return jsonify({"success": True, "path": path, "message": msg})

@app.route('/api/batch_logs', methods=['GET'])
def get_batch_logs():
    return jsonify({"running": is_batch_running, "logs": batch_logs})

@app.route('/api/batch_start', methods=['POST'])
def batch_start():
    data = request.json
    paths = data.get('paths', [])
    lang = data.get('language', 'nl')
    if is_batch_running: return jsonify({"success": False, "error": "Er draait al een batch!"})
    thread = threading.Thread(target=background_batch_processor, args=(paths, lang))
    thread.daemon = True
    thread.start()
    return jsonify({"success": True})

@app.route('/api/status', methods=['GET'])
def status():
    total_remaining = 0
    is_vip = False
    logged_in = False
    for api_key in API_KEYS:
        payload = {"username": OS_USER, "password": OS_PASS}
        headers = {"Api-Key": api_key, "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
        try:
            r = requests.post(f"{API_BASE}/login", json=payload, headers=headers)
            if r.status_code == 200:
                logged_in = True
                data = r.json().get('data', {})
                if data.get('vip'): is_vip = True
                total_remaining += data.get('remaining_downloads', 0)
        except: pass
    account_type = "⭐ Betaald / VIP" if is_vip else f"🆓 Gratis (Sleutels: {len(API_KEYS)})"
    return jsonify({"account_type": account_type, "remaining_downloads": total_remaining, "logged_in": logged_in})

@app.route('/api/contact', methods=['POST'])
def contact():
    if not AUTHOR_WEBHOOK or "PLAK_HIER" in AUTHOR_WEBHOOK: return jsonify({"success": False, "error": "Geen webhook."})
    msg = request.json.get('message', '').strip()
    if not msg: return jsonify({"success": False, "error": "Bericht leeg."})
    try:
        requests.post(AUTHOR_WEBHOOK, json={"embeds": [{"title": "📬 Contactbericht", "description": msg, "color": 3447003}]})
        return jsonify({"success": True})
    except Exception as e: return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)