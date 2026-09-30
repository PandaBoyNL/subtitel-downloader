import os, random, requests, re, subprocess, struct, time, threading
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

MEDIA_DIR = os.environ.get('MEDIA_DIR', '/media')
_api_keys_env = os.environ.get('OS_API_KEYS', '')
API_KEY = _api_keys_env.split(',')[0].strip() if _api_keys_env else ''

OS_USER = os.environ.get('OS_USERNAME', '')
OS_PASS = os.environ.get('OS_PASSWORD', '')
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')

AUTHOR_WEBHOOK = "https://discord.com/api/webhooks/1554654534360506430/pl5Fn-rxHXwoqxLQwdrGpobMhQFhR3-en3sabaOhndUzLng0s1LJEL5phECdztBJ2orS" 

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "UnraidSubDownloader v1.0"

batch_logs = []
is_batch_running = False
stop_batch_flag = False

def log_msg(msg, msg_type='info'):
    global batch_logs
    t = time.strftime('%d-%m-%Y %H:%M:%S')
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

def has_existing_subtitle(video_path, lang):
    base_path = os.path.splitext(video_path)[0]
    possible_srts = [f"{base_path}.srt", f"{base_path}.{lang}.srt"]
    if lang == 'nl':
        possible_srts.extend([f"{base_path}.nld.srt", f"{base_path}.dut.srt", f"{base_path}.dutch.srt"])
    elif lang == 'en':
        possible_srts.extend([f"{base_path}.eng.srt", f"{base_path}.english.srt"])
        
    for srt in possible_srts:
        if os.path.exists(srt): return True, "Extern SRT-bestand gevonden"
            
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream_tags=language", "-of", "csv=p=0", video_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if result.stdout:
            langs = [line.strip().lower() for line in result.stdout.split('\n') if line.strip()]
            search_langs = [lang.lower()]
            if lang == 'nl': search_langs.extend(['nld', 'dut', 'dutch'])
            elif lang == 'en': search_langs.extend(['eng', 'english'])
            for l in langs:
                if l in search_langs: return True, f"Ingebakken '{l.upper()}' track gevonden"
    except Exception: pass
    return False, ""

def send_discord_alert(title, description, color):
    if not DISCORD_WEBHOOK: return
    embed = {"title": title, "description": description, "color": color}
    try: requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10)
    except: pass

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
        embed["fields"].append({"name": f"⏭️ Overgeslagen ({len(skipped_list)})", "value": val})
    if failed_list:
        val = "\n".join(failed_list)
        if len(val) > 1000: val = val[:950] + "\n...(Lijst ingekort)"
        embed["fields"].append({"name": f"❌ Mislukt / Gestopt ({len(failed_list)})", "value": val})
    if not success_list and not failed_list and not skipped_list: embed["description"] = "Niets verwerkt."
    try: requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10)
    except: pass

def get_user_quota():
    if not API_KEY: return False, False, 0
    payload = {"username": OS_USER, "password": OS_PASS}
    headers = {"Api-Key": API_KEY, "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        r = requests.post(f"{API_BASE}/login", json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            token = r.json().get('token')
            auth_headers = {"Api-Key": API_KEY, "Authorization": f"Bearer {token}", "User-Agent": USER_AGENT, "Accept": "application/json"}
            user_r = requests.get(f"{API_BASE}/infos/user", headers=auth_headers, timeout=10)
            if user_r.status_code == 200:
                data = user_r.json().get('data', {})
                return True, data.get('vip', False), data.get('remaining_downloads', 0)
    except Exception:
        pass
    return False, False, 0

def internal_search(fullpath, lang):
    title, year, season, episode = get_best_search_terms(fullpath)
    abs_path = os.path.abspath(os.path.join(MEDIA_DIR, fullpath))
    file_hash = hashFile(abs_path) if os.path.exists(abs_path) else None
    
    def fetch_and_filter(prms, check_strict=True):
        if not API_KEY: return [], False
        valid = []
        headers = {"Api-Key": API_KEY, "User-Agent": USER_AGENT, "Accept": "application/json"}
        try:
            r = requests.get(f"{API_BASE}/subtitles", headers=headers, params=prms, timeout=10)
            if r.status_code == 429:
                time.sleep(3) 
                r = requests.get(f"{API_BASE}/subtitles", headers=headers, params=prms, timeout=10)
                if r.status_code == 429: return [], True 
                    
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
        except Exception:
            pass
            
        valid.sort(key=lambda x: x['sort_score'], reverse=True)
        return valid, False

    try:
        subs, search_term_display = [], ""
        if file_hash:
            search_term_display = f"Hash: {file_hash}"
            subs, is_limited = fetch_and_filter({"moviehash": file_hash, "languages": lang}, check_strict=False)
            if is_limited: return True, search_term_display, [], "API limiet bereikt"
            
        if not subs:
            search_term_display = f"Titel: '{title}' | Jaar: '{year}'"
            p3 = {"query": title, "languages": lang}
            if year: p3["year"] = year
            if season: p3["season_number"] = season
            if episode: p3["episode_number"] = episode
            subs, is_limited = fetch_and_filter(p3, check_strict=True)
            if is_limited: return True, search_term_display, [], "API limiet bereikt"
            
        if not subs and year:
            search_term_display = f"Titel: '{title} {year}'"
            p3b = {"query": f"{title} {year}", "languages": lang}
            if season: p3b["season_number"] = season
            if episode: p3b["episode_number"] = episode
            subs, is_limited = fetch_and_filter(p3b, check_strict=True)
            if is_limited: return True, search_term_display, [], "API limiet bereikt"
            
        if not subs and year:
            search_term_display = f"Titel: '{title}' (Zonder Jaar)"
            p4 = {"query": title, "languages": lang}
            if season: p4["season_number"] = season
            if episode: p4["episode_number"] = episode
            subs, is_limited = fetch_and_filter(p4, check_strict=True)
            if is_limited: return True, search_term_display, [], "API limiet bereikt"
            
        return False, search_term_display, subs, ""
    except Exception as e:
        return False, "", [], str(e)

def internal_download(file_id, video_path, lang):
    if not API_KEY: return False, False, "", "Geen API key gevonden."
    payload = {"username": OS_USER, "password": OS_PASS}
    headers = {"Api-Key": API_KEY, "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        login_r = requests.post(f"{API_BASE}/login", json=payload, headers=headers, timeout=10)
        if login_r.status_code != 200: return False, False, "", "Inloggen mislukt."
        
        token = login_r.json().get('token')
        dl_headers = {"Api-Key": API_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
        dl_r = requests.post(f"{API_BASE}/download", headers=dl_headers, json={"file_id": int(file_id)}, timeout=10)
        
        # DE FIX: We kijken NU pas naar woorden zoals 'remaining' als de statuscode NIET 200 OK is.
        if dl_r.status_code != 200:
            error_text = dl_r.text.lower()
            if dl_r.status_code in [406, 429] or 'limit' in error_text or 'remaining' in error_text or 'exceeded' in error_text:
                return False, True, "", "Dagelijkse downloadlimiet bereikt."
            return False, False, "", f"OpenSubtitles API Fout: {dl_r.status_code}"
            
        if dl_r.status_code == 200:
            link = dl_r.json().get('link')
            srt_data = requests.get(link, headers={"User-Agent": USER_AGENT}, timeout=15)
            if len(srt_data.content) < 50 or b'<html' in srt_data.content.lower():
                return False, False, "", "Corrupt bestand van OpenSubtitles."
            
            abs_video_path = os.path.join(MEDIA_DIR, video_path)
            srt_path = f"{os.path.splitext(abs_video_path)[0]}.{lang}.srt"
            with open(srt_path, 'wb') as f: f.write(srt_data.content)
            try:
                subprocess.run(["ffs", abs_video_path, "-i", srt_path, "-o", srt_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                msg = "✅ Perfect synchroon!"
            except Exception:
                msg = "⚠️ Originele timing behouden."
            
            return True, False, srt_path, msg
    except Exception as e:
        return False, False, "", str(e)
        
    return False, False, "", "Onbekende fout tijdens downloaden."

def background_batch_processor(paths, lang):
    global is_batch_running, stop_batch_flag
    is_batch_running = True
    stop_batch_flag = False
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
            if os.path.basename(full_path).lower() == 'featurettes': continue 
            
            for root, dirs, files in os.walk(full_path):
                dirs[:] = [d for d in dirs if d.lower() != 'featurettes']
                
                for file in files:
                    if file.lower().endswith(('.mkv', '.mp4', '.avi')):
                        if not file.startswith('.') and 'sample' not in file.lower():
                            fp = os.path.join(root, file)
                            found_files.append({"name": file, "path": os.path.relpath(fp, MEDIA_DIR)})
    
    log_msg(f"✅ Gevonden: {len(found_files)} video's om te verwerken.", "success")
    success_list = []
    failed_list = []
    skipped_list = []
    
    for item in found_files:
        if stop_batch_flag:
            log_msg("🛑 Batch handmatig afgebroken door gebruiker!", "warn")
            break

        fullpath = item['path']
        filename = item['name']
        abs_path = os.path.abspath(os.path.join(MEDIA_DIR, fullpath))
        
        exists, reason = has_existing_subtitle(abs_path, lang)
        if exists:
            log_msg(f"⏭️ Overslaan: {filename} ({reason})", "info")
            skipped_list.append(filename)
            continue
            
        log_msg(f"🎬 Starten met: {filename}", "info")
        
        is_rate_limited, search_term, subs, err = internal_search(fullpath, lang)
        
        if is_rate_limited:
            log_msg("⏳ API zoeklimiet bereikt. Batch gepauzeerd... (Druk op Stop om af te breken)", "warn")
            while True:
                if stop_batch_flag: break
                for _ in range(12): 
                    if stop_batch_flag: break
                    time.sleep(5)
                break
            if stop_batch_flag: break
            
            is_rate_limited, search_term, subs, err = internal_search(fullpath, lang)
            if is_rate_limited:
                log_msg(f"❌ Zoeken mislukt vanwege aanhoudende rate-limiet: {filename}", "error")
                failed_list.append(f"{filename} (Rate limit)")
                continue

        if not subs:
            log_msg(f"❌ Niet gevonden: {filename}", "error")
            failed_list.append(f"{filename} (Niet gevonden)")
            continue
            
        downloaded = False
        
        while not downloaded:
            if stop_batch_flag: break

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
                log_msg("⏳ Dagelijkse downloadlimiet bereikt. Batch gepauzeerd... (Druk op Stop om af te breken)", "warn")
                send_discord_alert("⏸️ Batch Gepauzeerd", "De dagelijkse limiet is bereikt. De app wacht nu op nieuwe downloads.", 16753920)
                
                while True:
                    if stop_batch_flag: break
                    
                    for _ in range(360): 
                        if stop_batch_flag: break
                        time.sleep(5)
                        
                    if stop_batch_flag: break
                        
                    success, is_vip, remaining = get_user_quota()
                    if success and remaining > 0:
                        log_msg(f"▶️ Limiet is gereset ({remaining} resterend)! Batch wordt hervat.", "success")
                        send_discord_alert("▶️ Batch Hervat", "Limieten gereset. Batch gaat verder!", 3066993)
                        break
                continue 
                
            if not downloaded and not rate_limited_dl:
                log_msg(f"❌ Download mislukt: {filename}", "error")
                failed_list.append(f"{filename} (Mislukt)")
                break
            
    if stop_batch_flag:
        log_msg("🛑 Batch definitief gestopt.", "warn")
    else:
        log_msg("🎉 Achtergrond-Batch is afgerond!", "success")
        
    send_discord_webhook(success_list, failed_list, skipped_list)
    is_batch_running = False
    stop_batch_flag = False

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/languages')
def get_languages():
    try:
        r = requests.get(f"{API_BASE}/infos/languages", headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=10)
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
            if entry.lower() == 'featurettes': continue
                
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
    if is_limit: return jsonify({"success": False, "rate_limited": True, "error": "API limiet bereikt!"})
    if err: return jsonify({"success": False, "search_term": search_term, "error": err})
    return jsonify({"success": True, "search_term": search_term, "data": subs})

@app.route('/api/download', methods=['POST'])
def download():
    data = request.json
    success, is_limit, path, msg = internal_download(data.get('file_id'), data.get('video_path'), data.get('language', 'nl'))
    if is_limit: return jsonify({"rate_limited": True, "error": "Download limiet bereikt."}), 429
    if not success: return jsonify({"error": msg}), 500
    return jsonify({"success": True, "path": path, "message": msg})

@app.route('/api/batch_logs', methods=['GET'])
def get_batch_logs():
    return jsonify({"running": is_batch_running, "logs": batch_logs})

@app.route('/api/batch_start', methods=['POST'])
def batch_start():
    global stop_batch_flag
    data = request.json
    paths = data.get('paths', [])
    lang = data.get('language', 'nl')
    if is_batch_running: return jsonify({"success": False, "error": "Er draait al een batch!"})
    stop_batch_flag = False
    thread = threading.Thread(target=background_batch_processor, args=(paths, lang))
    thread.daemon = True
    thread.start()
    return jsonify({"success": True})

@app.route('/api/batch_stop', methods=['POST'])
def batch_stop():
    global stop_batch_flag
    if is_batch_running:
        stop_batch_flag = True
    return jsonify({"success": True})

@app.route('/api/clear_logs', methods=['POST'])
def clear_logs():
    if not is_batch_running:
        batch_logs.clear()
    return jsonify({"success": True})

@app.route('/api/status', methods=['GET'])
def status():
    if not API_KEY:
        return jsonify({"account_type": "⚠ Geen API key ingesteld", "remaining_downloads": 0, "logged_in": False})
    
    success, is_vip, remaining = get_user_quota()
    if success:
        account_type = "⭐ VIP Account" if is_vip else "🆓 Gratis Account"
        return jsonify({"account_type": account_type, "remaining_downloads": remaining, "logged_in": True})
        
    return jsonify({"account_type": "⚠️ Fout bij inloggen", "remaining_downloads": 0, "logged_in": False})

@app.route('/api/contact', methods=['POST'])
def contact():
    if not AUTHOR_WEBHOOK or "PLAK_HIER" in AUTHOR_WEBHOOK: return jsonify({"success": False, "error": "Geen webhook."})
    msg = request.json.get('message', '').strip()
    if not msg: return jsonify({"success": False, "error": "Bericht leeg."})
    try:
        requests.post(AUTHOR_WEBHOOK, json={"embeds": [{"title": "📬 Contactbericht", "description": msg, "color": 3447003}]}, timeout=10)
        return jsonify({"success": True})
    except Exception as e: return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)