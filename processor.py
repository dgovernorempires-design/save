import os
import json
import yt_dlp
from google import genai  # Google GenAI SDK

def download_and_transcribe(video_url):
    print(f"[Worker] Downloading video from: {video_url}")
    
    # 1. Download video & extract audio using yt-dlp
    ydl_opts = {
        'format': 'bestvideo[height<=1080]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': 'downloads/source_video.mp4',
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        title = info.get('title', 'Unknown Title')

    print(f"[Worker] Download complete: {title}. Extracting transcript simulation / LLM analysis...")
    
    # 2. Call Gemini API to find viral moments (Controversial, Motivational, Inspirational)
    # Note: Pass your full transcript text here derived via Whisper or YouTube auto-subs
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
    
    # Parse AI response to get timestamp clips
    clips_data = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
    return clips_data

if __name__ == "__main__":
    # Test execution
    # download_and_transcribe("https://www.youtube.com/watch?v=EXAMPLE")
    pass

import subprocess
import os

def render_clip(source_video_path, start_sec, end_sec, output_filename, aspect_ratio="9:16"):
    print(f"[Worker] Processing clip: {start_sec}s to {end_sec}s -> {output_filename}")
    
    # Define resolution mapping
    if aspect_ratio == "9:16":
        # 1080x1920 vertical format with smart vertical scaling and cropping to center
        vf_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    elif aspect_ratio == "1:1":
        vf_filter = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
    else:
        vf_filter = "scale=1920:1080:force_original_aspect_ratio=decrease"

    duration = end_sec - start_sec
    output_path = os.path.join("outputs", output_filename)
    os.makedirs("outputs", exist_ok=True)

    # FFmpeg command to slice, crop, and re-encode efficiently
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

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"[Worker] Successfully rendered: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"[Worker Error] FFmpeg failed: {e.stderr.decode()}")
        return None
