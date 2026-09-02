const express = require('express');
const cors = require('cors');
const app = express();

app.use(express.json());
app.use(cors());

// Endpoint where your cPanel website sends the YouTube link & user settings
app.post('/api/process-video', async (req, res) => {
    try {
        const { videoUrl, targetRatio, styleSettings } = req.body;

        if (!videoUrl) {
            return res.status(400).json({ error: 'Video URL is required' });
        }

        // Generate a unique Job ID
        const jobId = 'job_' + Date.now();

        // TODO: Pass this job payload to your Python video processing worker or queue
        console.log(`[Job Queued] ID: ${jobId} | Target: ${videoUrl}`);

        return res.status(202).json({
            success: true,
            message: 'Video processing started successfully!',
            jobId: jobId,
            statusEndpoint: `/api/job-status/${jobId}`
        });

    } catch (error) {
        console.error('Queue Error:', error);
        return res.status(500).json({ error: 'Internal server error' });
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Backend bridge running on port ${PORT}`);
});
