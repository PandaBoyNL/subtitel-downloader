import os, random, requests, re, subprocess, struct
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

MEDIA_DIR = os.environ.get('MEDIA_DIR', '/media')
API_KEYS = [k.strip() for k in os.environ.get('OS_API_KEYS', '').split(',') if k.strip()]
OS_USER = os.environ.get('OS_USERNAME', '')
OS_PASS = os.environ.get('OS_PASSWORD', '')
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')
API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "UnraidSubDownloader v1.0"

def get_auth_token_and_key():
    last_error = ""
    for api_key in API_KEYS:
        payload = {"username": OS_USER, "password": OS_PASS}
        headers = {"Api-Key": api_key, "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
        try:
            r = requests.post(f"{API_BASE}/login", json=payload, headers=headers)
            if r.status_code == 200: return r.json().get('token'), api_key
            else: last_error = f"HTTP {r.status_code}: {r.text}"
        except Exception as e: last_error = str(e)
    return None, last_error

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
    paren_years = list(re.finditer(r'\((19\d{2}\vert{}20\d{2})\)', name))
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

@app.route('/')
def index(): return render_template('index.html')

# NIEUW: Haal alle beschikbare talen dynamisch op van OpenSubtitles!
@app.route('/api/languages')
def get_languages():
    try:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        r = requests.get(f"{API_BASE}/infos/languages", headers=headers)
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
            if os.path.isdir(f):
                items.append({"name": entry, "is_dir": True, "path": os.path.relpath(f, MEDIA_DIR)})
            elif entry.lower().endswith(('.mkv', '.mp4', '.avi')):
                if not entry.startswith('.') and 'sample' not in entry.lower():
                    items.append({"name": entry, "is_dir": False, "path": os.path.relpath(f, MEDIA_DIR)})
    return jsonify({"current_path": sub_path, "items": items})

@app.route('/api/scan', methods=['POST'])
def scan():
    paths = request.json.get('paths', [])
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
    return jsonify({"files": found_files})

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json
    fullpath = data.get('fullpath', data.get('filename'))
    original_filename = os.path.basename(fullpath)
    title, year, season, episode = get_best_search_terms(fullpath)
    
    abs_path = os.path.abspath(os.path.join(MEDIA_DIR, fullpath))
    file_hash = hashFile(abs_path) if os.path.exists(abs_path) else None
    
    api_key = random.choice(API_KEYS) if API_KEYS else ""
    headers = {"Api-Key": api_key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    
    def fetch_and_filter(prms, check_strict=True):
        try:
            r = requests.get(f"{API_BASE}/subtitles", headers=headers, params=prms)
            raw_subs = r.json().get('data', []) if r.status_code == 200 else []
        except: return []
        
        valid = []
        for sub in raw_subs:
            a = sub.get('attributes', {})
            release = str(a.get('release', '')).lower().replace('.', ' ').replace('-', ' ')
            feature = a.get('feature_details') or {}
            m_name = str(feature.get('movie_name', '')).lower()
            t_name = str(feature.get('title', '')).lower()
            
            score = int(a.get('download_count') or 0) + (float(a.get('ratings') or 0) * 1000)
            t_lower = title.lower()
            
            if check_strict:
                is_valid = False
                if len(t_lower) > 1 and (t_lower in m_name or m_name in t_lower or t_lower in t_name or t_name in t_lower or t_lower in release):
                    is_valid = True
                else:
                    words = [w for w in t_lower.split() if len(w) > 1]
                    if words and all((w in m_name or w in t_name or w in release) for w in words):
                        is_valid = True
                if not is_valid: continue
            
            if year:
                if str(year) == str(feature.get('year', '')): score += 10000000
                elif str(year) in release: score += 5000000
            if 'web' in release or 'bluray' in release: score += 50000
            sub['sort_score'] = score
            valid.append(sub)
            
        valid.sort(key=lambda x: x['sort_score'], reverse=True)
        return valid

    try:
        subs = []
        search_term_display = ""
        lang = data.get('language', 'nl')
        
        if file_hash:
            search_term_display = f"Hash: {file_hash}"
            subs = fetch_and_filter({"moviehash": file_hash, "languages": lang}, check_strict=False)
            
        if not subs:
            search_term_display = f"Titel: '{title}' | Jaar: '{year}'"
            p3 = {"query": title, "languages": lang}
            if year: p3["year"] = year
            if season: p3["season_number"] = season
            if episode: p3["episode_number"] = episode
            subs = fetch_and_filter(p3, check_strict=True)
            
        if not subs and year:
            search_term_display = f"Titel: '{title}' (Zonder Jaar)"
            p4 = {"query": title, "languages": lang}
            if season: p4["season_number"] = season
            if episode: p4["episode_number"] = episode
            subs = fetch_and_filter(p4, check_strict=True)

        return jsonify({"success": True, "search_term": search_term_display, "data": subs})
    except Exception as e: return jsonify({"success": False, "search_term": search_term_display, "error": str(e)})

@app.route('/api/download', methods=['POST'])
def download():
    data = request.json
    token, working_key_or_error = get_auth_token_and_key()
    if not token: return jsonify({"error": f"API Login Error: {working_key_or_error}"}), 401
    headers = {"Api-Key": working_key_or_error, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
    dl_r = requests.post(f"{API_BASE}/download", headers=headers, json={"file_id": int(data.get('file_id'))})
    
    if dl_r.status_code == 200:
        link = dl_r.json().get('link')
        srt_data = requests.get(link, headers={"User-Agent": USER_AGENT})
        if len(srt_data.content) < 50 or b'<html' in srt_data.content.lower() or b'<body' in srt_data.content.lower():
            return jsonify({"error": "Corrupt file from OpenSubtitles."}), 500
        video_path = os.path.join(MEDIA_DIR, data.get('video_path'))
        srt_path = f"{os.path.splitext(video_path)[0]}.{data.get('language', 'nl')}.srt"
        with open(srt_path, 'wb') as f: f.write(srt_data.content)
        try:
            subprocess.run(["ffs", video_path, "-i", srt_path, "-o", srt_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            msg = f"✅ Perfect synchroon!"
        except:
            msg = f"⚠️ Originele timing behouden."
        return jsonify({"success": True, "path": srt_path, "message": msg})
    return jsonify({"error": f"Status {dl_r.status_code}: {dl_r.text}"}), 500

@app.route('/api/notify', methods=['POST'])
def notify():
    if not DISCORD_WEBHOOK: return jsonify({"status": "no_webhook"})
    data = request.json
    success_list = data.get('success', [])
    failed_list = data.get('failed', [])
    
    embed = {"title": "🎬 Subtitel downloader: Batch Voltooid!", "color": 3066993 if len(failed_list) == 0 else 15158332, "fields": []}
    if success_list:
        val = "\n".join(success_list)
        if len(val) > 1000: val = val[:950] + "\n...(Lijst ingekort)"
        embed["fields"].append({"name": f"✅ Succesvol ({len(success_list)})", "value": val})
    if failed_list:
        val = "\n".join(failed_list)
        if len(val) > 1000: val = val[:950] + "\n...(Lijst ingekort)"
        embed["fields"].append({"name": f"❌ Mislukt ({len(failed_list)})", "value": val})
        
    if not success_list and not failed_list: embed["description"] = "Niets verwerkt."
    try:
        requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]})
        return jsonify({"status": "sent"})
    except: return jsonify({"status": "error"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
