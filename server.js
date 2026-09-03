const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const app = express();
app.use(express.json());
app.use(cors());

// Configuration
const CPANEL_WEBHOOK_URL = process.env.CPANEL_WEBHOOK_URL || 'https://yourdomain.com/webhook.php';
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || 'YOUR_SECURE_WEBHOOK_SECRET';

// In-memory job state store
const jobStatuses = {};
let isProcessingActive = false; // Strict concurrency lock for 512MB RAM protection

// Health endpoint for Render uptime monitoring
app.get('/health', (req, res) => {
    res.status(200).json({ 
        status: 'healthy', 
        activeJob: isProcessingActive,
        uptime: process.uptime() 
    });
});

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

// Start Video Processing Endpoint
app.post('/api/process-video', async (req, res) => {
    try {
        const { videoUrl, targetRatio } = req.body;
        if (!videoUrl) return res.status(400).json({ error: 'Video URL is required' });

        // Enforce single-job queue limit to prevent OOM crashes on Render
        if (isProcessingActive) {
            return res.status(429).json({ 
                error: 'Server is currently processing another video. Please try again shortly.' 
            });
        }

        const jobId = 'job_' + Date.now();
        jobStatuses[jobId] = { progress: 2, message: 'Job queued...', status: 'queued' };
        
        console.log(`[Job Queued] ID: ${jobId} | Target: ${videoUrl}`);
        await ensureYtDlp();

        isProcessingActive = true;

        // Spawn Python worker
        const pythonProcess = spawn('python3', ['processor.py', videoUrl, jobId, targetRatio || '9:16']);

        pythonProcess.stdout.on('data', (data) => {
            const output = data.toString().trim();
            console.log(`[Python ${jobId}]: ${output}`);

            const match = output.match(/\[PROGRESS:\s*(\d+)%\]/);
            if (match) {
                const percent = parseInt(match[1]);
                jobStatuses[jobId] = { progress: percent, message: output, status: 'processing' };
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            console.error(`[Python Error ${jobId}]: ${data.toString().trim()}`);
        });

        pythonProcess.on('close', (code) => {
            isProcessingActive = false; // Release lock

            if (code === 0) {
                // Check if final results were saved/reported
                const currentJob = jobStatuses[jobId];
                if (!currentJob || currentJob.status !== 'completed') {
                    jobStatuses[jobId] = { 
                        progress: 100, 
                        message: 'Processing complete!', 
                        status: 'completed'
                    };
                }
            } else {
                jobStatuses[jobId] = { 
                    progress: 100, 
                    message: 'Processing failed during execution.', 
                    status: 'failed' 
                };
            }
        });

        return res.status(202).json({ success: true, jobId: jobId, message: 'Processing started.' });

    } catch (error) {
        isProcessingActive = false;
        console.error('Queue Error:', error);
        return res.status(500).json({ error: error.message });
    }
});

// Job Status Endpoint
app.get('/api/job-status/:jobId', (req, res) => {
    const { jobId } = req.params;
    const job = jobStatuses[jobId];

    if (!job) {
        return res.status(404).json({ error: 'Job not found or expired.' });
    }

    return res.json(job);
});

// Internal webhook receiver for Python worker to sync clips directly
app.post('/api/internal-sync', (req, res) => {
    const { jobId, clips } = req.body;
    if (!jobId || !clips) {
        return res.status(400).json({ error: 'Invalid payload' });
    }

    jobStatuses[jobId] = {
        progress: 100,
        message: 'Processing complete!',
        status: 'completed',
        clips: clips
    };

    console.log(`[Sync] Job ${jobId} successfully registered ${clips.length} clips.`);
    return res.json({ success: true });
});

const PORT = process.env.PORT || 10000;
app.listen(PORT, '0.0.0.0', async () => {
    console.log(`Backend bridge running on port ${PORT}`);
    try { await ensureYtDlp(); } catch (e) {}
});
