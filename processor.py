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

import whisper
import subprocess
import os

def generate_subtitles_and_mix_audio(clip_video_path, audio_output_path):
    print(f"[Worker] Transcribing clip for word-level captions: {clip_video_path}")
    
    # 1. Load tiny/base whisper model to get word timings
    model = whisper.load_model("base")
    result = model.transcribe(clip_video_path, word_timestamps=True)
    
    # 2. Build an Advanced SubStation Alpha (.ass) subtitle content with modern styling (large bold centered text)
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

    # Extract word segments into subtitle events
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            start_str = format_time(word_info["start"])
            end_str = format_time(word_info["end"])
            word_text = word_info["word"].strip().upper()
            
            # Add each highlighted word event to the ASS script
            ass_content += f"Dialogue: 0,{start_str},{end_str},ViralStyle,,0,0,0,,{word_text}\n"

    ass_path = clip_video_path.replace(".mp4", ".ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    print(f"[Worker] Subtitles written. Rendering final video with background music mix...")
    
    # 3. Burn subtitles permanently into video and mix background music loop using FFmpeg
    final_output = audio_output_path
    bg_music = "background_beat.mp3" # optional background track
    
    if os.path.exists(bg_music):
        # Complex filter: burn subs, lower background music volume to 10%, mix with original speech audio
        cmd = [
            "ffmpeg", "-y",
            "-i", clip_video_path,
            "-i", bg_music,
            "-filter_complex",
            f"[0:v]subtitles={ass_path}[v];[1:a]volume=0.1[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264", "preset", "fast",
            "-c:a", "aac",
            final_output
        ]
    else:
        # Just burn subtitles if no background music file is provided
        cmd = [
            "ffmpeg", "-y",
            "-i", clip_video_path,
            "-vf", f"subtitles={ass_path}",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "copy",
            final_output
        ]

    subprocess.run(cmd, check=True)
    print(f"[Worker] Complete captioned short ready: {final_output}")
    return final_output
