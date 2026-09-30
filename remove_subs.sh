#!/bin/bash
trap '' PIPE

SEARCH_DIR="${1:-/media}"
WEBHOOK_URL="${DISCORD_WEBHOOK}"

# Deze functie plaatst altijd netjes de huidige datum/tijd vooraan
t_echo() {
    echo "[$(date +'%d-%m-%Y %H:%M:%S')] $1"
}

LANG_ENV="${LANG:-nl}"
if [[ "${LANG_ENV,,}" == *"nl"* ]]; then
    S_SEARCH="🔍 Zoeken naar mkv/mp4 video's in"
    S_SCAN="👀 [SCAN] Controleer:"
    S_MATCH="       -> 🎯 [MATCH] Ondertiteling gevonden! Starten met strippen ✂️..."
    S_SUCCES="       -> ✅ [SUCCES] Ondertiteling verwijderd. Bestand overschreven 🎬."
    S_FOUT="       -> ❌ [FOUT] Iets ging mis. Origineel blijft behouden."
    S_SKIP="       -> ⏭️ [SKIP] Geen ingebakken ondertiteling."
    S_KLAAR="🎉 Klaar met scannen en strippen!"
    S_DISCORD="✅ Het scannen en strippen in de map \`$SEARCH_DIR\` is succesvol afgerond!"
else
    S_SEARCH="🔍 Searching for mkv/mp4 videos in"
    S_SCAN="👀 [SCAN] Checking:"
    S_MATCH="       -> 🎯 [MATCH] Subtitles found! Starting extraction ✂️..."
    S_SUCCES="       -> ✅ [SUCCESS] Subtitles removed. File overwritten 🎬."
    S_FOUT="       -> ❌ [ERROR] Something went wrong. Original kept."
    S_SKIP="       -> ⏭️ [SKIP] No hardcoded subtitles."
    S_KLAAR="🎉 Finished scanning and stripping!"
    S_DISCORD="✅ Scanning and stripping in folder \`$SEARCH_DIR\` completed successfully!"
fi

t_echo "$S_SEARCH$SEARCH_DIR..."
t_echo "---------------------------------------------------"

find "$SEARCH_DIR" -type f \( -iname "*.mkv" -o -iname "*.mp4" \) | while read -r file; do
    t_echo "$S_SCAN$file"
    
    SUBS=$(ffprobe -loglevel error -probesize 100M -analyzeduration 100M -select_streams s -show_entries stream=index -of csv=p=0 "$file")

    if [ -n "$SUBS" ]; then
        t_echo "$S_MATCH"
        temp_file="${file%.*}_temp.${file##*.}"

        ffmpeg -nostdin -probesize 100M -analyzeduration 100M -i "$file" -c copy -sn "$temp_file" -y -loglevel error

        if [ $? -eq 0 ]; then
            t_echo "$S_SUCCES"
            mv -f "$temp_file" "$file"
            chown 99:100 "$file" 2>/dev/null
            chmod 0666 "$file" 2>/dev/null
        else
            t_echo "$S_FOUT"
            rm -f "$temp_file"
        fi
    else
        t_echo "$S_SKIP"
    fi
done

t_echo "---------------------------------------------------"
t_echo "$S_KLAAR"

if [ -n "$WEBHOOK_URL" ]; then
    curl -s -H "Content-Type: application/json" \
         -X POST \
         -d "{\"content\": \"🎬 **SUB-GONE** 🍿\n$S_DISCORD\"}" \
         "$WEBHOOK_URL" > /dev/null
fi
