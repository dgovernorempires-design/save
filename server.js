const express = require('express');
const fs = require('fs');
const { execSync, spawn } = require('child_process');
const path = require('path');

const app = express();
// Enable CORS for all incoming requests from your cPanel frontend
app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.header('Access-Control-Allow-Headers', 'Content-Type, X-Top-Text, X-Bottom-Text');
    if (req.method === 'OPTIONS') {
        return res.sendStatus(200);
    }
    next();
});
const PORT = process.env.PORT || 10000;

app.use(express.json());
app.use('/downloads', express.static(path.join(__dirname, 'downloads')));

// Ensure downloads directory exists
const downloadsDir = path.join(__dirname, 'downloads');
if (!fs.existsSync(downloadsDir)) {
    fs.mkdirSync(downloadsDir, { recursive: true });
}

// Robustly download the official Linux binary for yt-dlp if it doesn't exist
const ytDlpPath = path.join('/tmp', 'yt-dlp');
if (!fs.existsSync(ytDlpPath)) {
    console.log("[Setup] Downloading official Linux yt-dlp binary to /tmp...");
    try {
        execSync(`curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ${ytDlpPath}`, { stdio: 'inherit' });
        execSync(`chmod +x ${ytDlpPath}`, { stdio: 'inherit' });
        console.log("[Setup] yt-dlp successfully downloaded and configured for Linux.");
    } catch (err) {
        console.error("[Setup Error] Failed to download yt-dlp binary:", err.message);
    }
}

// In-memory job tracking store
const jobs = {};

app.get('/health', (req, res) => {
    res.json({ status: 'healthy', activeJob: false, uptime: process.uptime() });
});

// Process Video URL Endpoint
app.post('/api/process-video', (req, res) => {
    const { videoUrl, topText, topBg, topHeight, bottomText, bottomBg } = req.body;
    if (!videoUrl) return res.status(400).json({ error: 'Video URL is required' });

    const jobId = 'job_' + Date.now();
    jobs[jobId] = { status: 'processing', progress: 10, message: 'Job queued...', clips: [] };

    console.log(`[Job Queued] ID: ${jobId} | Target: ${videoUrl}`);
    runProcessor(jobId, videoUrl, topText, topBg, topHeight, bottomText, bottomBg);

    res.json({ jobId });
});

// Process File Upload Endpoint with decoded headers for emojis
app.post('/api/process-upload', (req, res) => {
    const jobId = 'job_' + Date.now();
    const localSource = path.join(downloadsDir, `source_${jobId}.mp4`);
    // Also save as fallback generic name for processor.py
    const legacySource = path.join(downloadsDir, 'source_video.mp4');
    
    const fileStream = fs.createWriteStream(localSource);

    const topText = decodeURIComponent(req.headers['x-top-text'] || 'MUST WATCH MOMENT');
    const bottomText = decodeURIComponent(req.headers['x-bottom-text'] || '@DgovernorEmpire');

    req.pipe(fileStream);

    fileStream.on('finish', () => {
        // Copy to legacy path for compatibility
        try {
            fs.copyFileSync(localSource, legacySource);
        } catch (e) {}

        jobs[jobId] = { status: 'processing', progress: 10, message: 'Upload received, queueing worker...', clips: [] };
        console.log(`[Upload Job Queued] ID: ${jobId}`);
        runProcessor(jobId, 'local_upload', topText, 'red', '200', bottomText, 'green');
        res.json({ jobId });
    });

    fileStream.on('error', (err) => {
        console.error('[Upload Error]:', err);
        res.status(500).json({ error: 'Failed to save uploaded file' });
    });
});

// Internal sync from python worker
app.post('/api/internal-sync', (req, res) => {
    const { jobId, clips } = req.body;
    if (jobs[jobId]) {
        jobs[jobId].status = 'completed';
        jobs[jobId].progress = 100;
        jobs[jobId].message = 'Processing Complete!';
        jobs[jobId].clips = clips || [];
        console.log(`[Job Completed] ID: ${jobId}`);
    }
    res.json({ success: true });
});

// Status check endpoint
app.get('/api/job-status/:jobId', (req, res) => {
    const job = jobs[req.params.jobId];
    if (!job) return res.status(404).json({ error: 'Job not found' });
    res.json(job);
});

function runProcessor(jobId, videoUrl, topText, topBg, topHeight, bottomText, bottomBg) {
    const pythonProcess = spawn('python3', [
        'processor.py',
        videoUrl,
        jobId,
        topText || 'MUST WATCH MOMENT',
        topBg || 'red',
        bottomText || '@DgovernorEmpire',
        bottomBg || 'green'
    ]);

    pythonProcess.stdout.on('data', (data) => {
        const output = data.toString().trim();
        console.log(`[Python ${jobId}]: ${output}`);
        const match = output.match(/\[PROGRESS:\s*(\d+)\%\]/);
        if (match && jobs[jobId]) {
            jobs[jobId].progress = parseInt(match[1], 10);
            jobs[jobId].message = output;
        }
    });

    pythonProcess.stderr.on('data', (data) => {
        console.error(`[Python Error ${jobId}]: ${data.toString()}`);
    });

    pythonProcess.on('close', (code) => {
        if (code !== 0 && jobs[jobId] && jobs[jobId].status !== 'completed') {
            jobs[jobId].status = 'failed';
            jobs[jobId].message = 'Worker execution failed.';
        }
    });
}

app.listen(PORT, () => {
    console.log(`Backend bridge running on port ${PORT}`);
});
