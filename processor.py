import os
import sys
import json
import subprocess
import urllib.request
from PIL import Image, ImageDraw, ImageFont
import whisper
import yt_dlp
from google import genai

# 1. Download Video and Extract Title / Content
def download_and_transcribe(video_url):
    print(f"[PROGRESS: 10%] Downloading video from: {video_url}")
    
    ydl_opts = {
        'format': 'bestvideo[height<=1080]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': 'downloads/source_video.mp4',
    }
    
    os.makedirs("downloads", exist_ok=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        title = info.get('title', 'Unknown Title')

    print(f"[PROGRESS: 30%] Download complete: {title}. Analyzing with Gemini AI...")
    
    # 2. Call Gemini API to find viral moments
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    
    prompt = f"""
    Analyze this video title and context: '{title}'. 
    You are an expert short-form content creator. Identify 3 to 5 high-impact, 
    attention-grabbing segments (30 to 90 seconds long) that are motivational, 
    controversial, or inspirational.
    
    Return ONLY a valid JSON array of objects with start_sec, end_sec, and hook_title:
    [
      {{"start_sec": 120, "end_sec": 185, "hook_title": "The Mindset Shift"}}
    ]
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    
    try:
        clean_json = response.text.strip().replace("```json", "").replace("```", "")
        clips_data = json.loads(clean_json)
    except Exception as e:
        print(f"[Worker Error] Failed to parse Gemini JSON: {e}")
        clips_data = [{"start_sec": 0, "end_sec": 60, "hook_title": "Key Takeaway"}]
        
    return "downloads/source_video.mp4", clips_data

# 3. Render Clip via FFmpeg
def render_clip(source_video_path, start_sec, end_sec, output_filename, aspect_ratio="9:16"):
    print(f"[Worker] Processing clip: {start_sec}s to {end_sec}s -> {output_filename}")
    
    if aspect_ratio == "9:16":
        vf_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    elif aspect_ratio == "1:1":
        vf_filter = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
    else:
        vf_filter = "scale=1920:1080:force_original_aspect_ratio=decrease"

    duration = end_sec - start_sec
    output_path = os.path.join("outputs", output_filename)
    os.makedirs("outputs", exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", source_video_path,
        "-t", str(duration),
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_path

# 4. Generate Subtitles and Burn via Whisper (using 'tiny' to prevent memory crashes)
def generate_subtitles_and_mix_audio(clip_video_path, audio_output_path):
    print(f"[Worker] Transcribing clip for word-level captions...")
    
    model = whisper.load_model("tiny")
    result = model.transcribe(clip_video_path, word_timestamps=True)
    
    ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ViralStyle,Arial,70,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,10,10,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def format_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"

    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            start_str = format_time(word_info["start"])
            end_str = format_time(word_info["end"])
            word_text = word_info["word"].strip().upper()
            ass_content += f"Dialogue: 0,{start_str},{end_str},ViralStyle,,0,0,0,,{word_text}\n"

    ass_path = clip_video_path.replace(".mp4", ".ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    cmd = [
        "ffmpeg", "-y",
        "-i", clip_video_path,
        "-vf", f"subtitles={ass_path}",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "copy",
        audio_output_path
    ]

    subprocess.run(cmd, check=True)
    return audio_output_path

# 5. Dispatch Webhook to cPanel Storage
def send_clips_to_cpanel(job_id, clips_array):
    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        print("[Webhook Error] WEBHOOK_URL environment variable is missing on Render!")
        return

    secret_token = "YOUR_SECURE_WEBHOOK_SECRET" 
    payload = {
        "jobId": job_id,
        "clips": clips_array
    }

    req = urllib.request.Request(
        webhook_url, 
        data=json.dumps(payload).encode('utf-8'),
        method='POST'
    )
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Webhook-Secret', secret_token)

    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
            print(f"[Webhook Success]: {res_body}")
    except Exception as e:
        print(f"[Webhook Failed]: {str(e)}")

# Main Execution Flow
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 processor.py <videoUrl> <jobId> [targetRatio]")
        sys.exit(1)

    video_url = sys.argv[1]
    job_id = sys.argv[2]
    target_ratio = sys.argv[3] if len(sys.argv) > 3 else "9:16"

    try:
        # Step 1: Download & AI Analysis
        source_video, clips_meta = download_and_transcribe(video_url)
        
        print(f"[PROGRESS: 60%] Rendering clips with FFmpeg...")
        generated_clips = []
        
        # Step 2: Loop and process each clip segment
        for idx, clip in enumerate(clips_meta):
            clip_filename = f"clip_{idx+1}_{job_id}.mp4"
            raw_clip_path = render_clip(source_video, clip['start_sec'], clip['end_sec'], clip_filename, target_ratio)
            
            print(f"[PROGRESS: 80%] Adding subtitles to clip {idx+1}...")
            final_clip_path = generate_subtitles_and_mix_audio(raw_clip_path, raw_clip_path.replace(".mp4", "_captioned.mp4"))
            
            # Construct public download link pointing to the auto-deleting stream endpoint
            render_domain = os.environ.get("RENDER_EXTERNAL_URL", "https://save-l1w3.onrender.com")
            public_url = f"{render_domain}/api/download/{os.path.basename(final_clip_path)}"
            
            generated_clips.append({
                "title": clip.get('hook_title', f"Viral Clip #{idx+1}"),
                "url": public_url
            })

        print(f"[PROGRESS: 95%] Syncing completed clips to cPanel storage...")
        
        # Step 3: Send back results via Webhook to cPanel
        send_clips_to_cpanel(job_id, generated_clips)

        print("[PROGRESS: 100%] All clips generated successfully!")

    except Exception as e:
        print(f"[Worker Fatal Error]: {str(e)}")
        sys.exit(1)
