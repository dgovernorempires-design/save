import os
import sys
import json
import subprocess
import urllib.request
import urllib.parse
import gc
from PIL import Image, ImageDraw, ImageFont
import whisper
import yt_dlp
from google import genai

# 1. Download Video and Transcribe Once
def download_and_transcribe(video_url):
    print(f"[PROGRESS: 10%] Downloading video source via yt-dlp...")

    ydl_opts = {
        'format': 'best[height<=720]/best',
        'outtmpl': 'downloads/source_video.mp4',
        'max_filesize': 200 * 1024 * 1024, # Limit to 200MB to protect server limits
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb'] # Mobile web client bypasses desktop bot-detection walls cleanly
            }
        }
    }
    
    os.makedirs("downloads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            title = info.get('title', 'Unknown Title')
    except Exception as e:
        raise RuntimeError(f"Failed to download video with yt-dlp: {str(e)}")

    print(f"[PROGRESS: 35%] Loading Whisper model (tiny) to transcribe audio once...")
    try:
        # Using 'tiny' model strictly to prevent OOM crashes on restricted RAM tiers
        model = whisper.load_model("tiny")
        result = model.transcribe("downloads/source_video.mp4", word_timestamps=True)
    except Exception as e:
        raise RuntimeError(f"Whisper transcription failed: {str(e)}")
    finally:
        # Unload Whisper model explicitly to free up RAM immediately
        if 'model' in locals():
            del model
        gc.collect()

    print(f"[PROGRESS: 50%] Transcription complete. Analyzing transcript with Gemini AI...")
    return "downloads/source_video.mp4", title, result
    
# 2. Analyze Transcript with Gemini
def analyze_transcript_with_gemini(title, transcript_result):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")
        
    client = genai.Client(api_key=api_key)
    
    full_text = " ".join([seg.get("text", "") for seg in transcript_result.get("segments", [])])
    truncated_text = full_text[:12000] # Safe token limit window

    prompt = f"""
    Video Title: '{title}'
    Transcript snippet: "{truncated_text}"

    You are an expert short-form content creator. Identify 3 to 4 high-impact, 
    attention-grabbing segments (30 to 60 seconds long) based on the actual spoken transcript.
    
    Return ONLY a valid JSON array of objects with start_sec, end_sec, and hook_title:
    [
      {{"start_sec": 45, "end_sec": 95, "hook_title": "The Core Breakthrough"}}
    ]
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        clean_json = response.text.strip().replace("```json", "").replace("```", "")
        clips_data = json.loads(clean_json)
    except Exception as e:
        print(f"[Worker Warning] Gemini parsing failed ({e}). Falling back to default split.")
        clips_data = [{"start_sec": 0, "end_sec": 45, "hook_title": "Key Highlight"}]
        
    return clips_data

# 3. Render Clip via FFmpeg & Burn Subtitles
def render_and_caption_clip(source_video_path, clip_meta, idx, job_id, target_ratio, full_transcript):
    start_sec = clip_meta['start_sec']
    end_sec = clip_meta['end_sec']
    duration = end_sec - start_sec
    
    print(f"[PROGRESS: {60 + (idx * 10)}%] Processing clip {idx+1}: {start_sec}s - {end_sec}s")

    if target_ratio == "9:16":
        vf_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    elif target_ratio == "1:1":
        vf_filter = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
    else:
        vf_filter = "scale=1920:1080:force_original_aspect_ratio=decrease"

    raw_output = f"outputs/raw_clip_{idx+1}_{job_id}.mp4"
    final_output = f"outputs/clip_{idx+1}_{job_id}_captioned.mp4"

    # Step A: Cut specific clip section with FFmpeg
    cmd_cut = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", source_video_path,
        "-t", str(duration),
        "-vf", vf_filter,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        raw_output
    ]
    
    result = subprocess.run(cmd_cut, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg cutting failed: {result.stderr.decode('utf-8', errors='ignore')}")

    # Step B: Generate ASS subtitles script
    ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ViralStyle,Arial,75,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,10,10,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def format_time(seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h}:{m:02d}:{s:02d}.{ms:03d}"

    for segment in full_transcript.get("segments", []):
        for w in segment.get("words", []):
            w_start = w["start"]
            w_end = w["end"]
            if w_start >= start_sec and w_end <= end_sec:
                rel_start = w_start - start_sec
                rel_end = w_end - start_sec
                word_text = w["word"].strip().upper()
                ass_content += f"Dialogue: 0,{format_time(rel_start)},{format_time(rel_end)},ViralStyle,,0,0,0,,{word_text}\n"

    ass_path = f"outputs/sub_{idx}_{job_id}.ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    # Step C: Burn subtitles into the clip using FFmpeg filter escape rules for file paths
    safe_ass_path = ass_path.replace(":", "\\:") if os.name == 'nt' else ass_path
    
    cmd_burn = [
        "ffmpeg", "-y",
        "-i", raw_output,
        "-vf", f"subtitles='{safe_ass_path}'",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "copy",
        final_output
    ]
    
    burn_result = subprocess.run(cmd_burn, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if burn_result.returncode != 0:
        print(f"[Warning] Subtitle burn failed, using raw uncaptioned clip: {burn_result.stderr.decode('utf-8', errors='ignore')}")
        if os.path.exists(raw_output):
            os.replace(raw_output, final_output)

    # Clean intermediate temp files
    for p in [raw_output, ass_path]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except:
                pass

    return final_output

# 4. Upload to cPanel & Notify Node Server
def upload_clip_to_cpanel(file_path, clip_title, job_id):
    cpanel_upload_url = os.environ.get("CPANEL_UPLOAD_URL", "https://yourdomain.com/upload-handler.php")
    secret_token = os.environ.get("WEBHOOK_SECRET", "YOUR_SECURE_WEBHOOK_SECRET")

    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_data = f.read()

    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"jobId\"\r\n\r\n{job_id}\r\n"
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"title\"\r\n\r\n{clip_title}\r\n"
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"video\"; filename=\"{filename}\"\r\n"
        f"Content-Type: video/mp4\r\n\r\n"
    ).encode('utf-8') + file_data + f"\r\n--{boundary}--\r\n".encode('utf-8')

    req = urllib.request.Request(cpanel_upload_url, data=body, method='POST')
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    req.add_header('X-Webhook-Secret', secret_token)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            return res_json.get("url")
    except Exception as e:
        print(f"[Upload Error]: {e}")
        return None

# Main Execution Flow
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 processor.py <videoUrl> <jobId> [targetRatio]")
        sys.exit(1)

    video_url = sys.argv[1]
    job_id = sys.argv[2]
    target_ratio = sys.argv[3] if len(sys.argv) > 3 else "9:16"

    try:
        source_video, title, transcript_result = download_and_transcribe(video_url)
        
        print(f"[PROGRESS: 55%] Identifying viral highlights with Gemini...")
        clips_meta = analyze_transcript_with_gemini(title, transcript_result)
        
        generated_clips = []
        for idx, clip_meta in enumerate(clips_meta[:4]):
            final_path = render_and_caption_clip(source_video, clip_meta, idx, job_id, target_ratio, transcript_result)
            
            print(f"[PROGRESS: 90%] Uploading clip {idx+1} to cPanel storage...")
            cpanel_url = upload_clip_to_cpanel(final_path, clip_meta.get('hook_title', f"Viral Clip #{idx+1}"), job_id)
            
            if cpanel_url:
                generated_clips.append({
                    "title": clip_meta.get('hook_title', f"Viral Clip #{idx+1}"),
                    "url": cpanel_url
                })
            
            if os.path.exists(final_path):
                os.remove(final_path)

        if os.path.exists(source_video):
            os.remove(source_video)

        print(f"[PROGRESS: 98%] Syncing completion status with Node server...")
        sync_payload = json.dumps({"jobId": job_id, "clips": generated_clips}).encode('utf-8')
        port = os.environ.get('PORT', '10000')
        sync_req = urllib.request.Request(f"http://localhost:{port}/api/internal-sync", data=sync_payload, method='POST')
        sync_req.add_header('Content-Type', 'application/json')
        
        try:
            urllib.request.urlopen(sync_req, timeout=10)
        except Exception as sync_err:
            print(f"[Warning] Failed to sync internally with Node server: {sync_err}")

        print("[PROGRESS: 100%] All clips generated and synced successfully!")

    except Exception as e:
        print(f"[Worker Fatal Error]: {str(e)}")
        sys.exit(1)
