const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

const app = express();

app.use(express.json());
app.use(cors());

// Helper: Ensure yt-dlp is dynamically downloaded to /tmp for Render environments
async function ensureYtDlp() {
    const ytDlpPath = path.join('/tmp', 'yt-dlp');
    if (!fs.existsSync(ytDlpPath)) {
        console.log('[Setup] Downloading yt-dlp to /tmp...');
        return new Promise((resolve, reject) => {
            const file = fs.createWriteStream(ytDlpPath);
            https.get('https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp', (response) => {
                response.pipe(file);
                file.on('finish', () => {
                    file.close(() => {
                        fs.chmodSync(ytDlpPath, '755');
                        console.log('[Setup] yt-dlp downloaded and made executable.');
                        resolve(ytDlpPath);
                    });
                });
            }).on('error', (err) => {
                fs.unlink(ytDlpPath, () => {});
                reject(err);
            });
        });
    }
    return ytDlpPath;
}

// Endpoint where your cPanel website sends the YouTube link & user settings
app.post('/api/process-video', async (req, res) => {
    try {
        const { videoUrl, targetRatio, styleSettings } = req.body;

        if (!videoUrl) {
            return res.status(400).json({ error: 'Video URL is required' });
        }

        // Generate a unique Job ID
        const jobId = 'job_' + Date.now();
        console.log(`[Job Queued] ID: ${jobId} | Target: ${videoUrl}`);

        // Ensure yt-dlp is ready before handling job execution
        await ensureYtDlp();

        // Spawn the Python processing worker in the background
        const pythonProcess = spawn('python3', ['processor.py', videoUrl, jobId, targetRatio || '9:16'], {
            detached: true,
            stdio: 'ignore'
        });
        pythonProcess.unref();

        return res.status(202).json({
            success: true,
            message: 'Video processing started successfully in the background!',
            jobId: jobId,
            statusEndpoint: `/api/job-status/${jobId}`
        });

    } catch (error) {
        console.error('Queue Error:', error);
        return res.status(500).json({ error: 'Internal server error: ' + error.message });
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, async () => {
    console.log(`Backend bridge running on port ${PORT}`);
    try {
        await ensureYtDlp();
    } catch (e) {
        console.error('Startup yt-dlp initialization warning:', e.message);
    }
});
