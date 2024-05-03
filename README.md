# rtsp-timelapse
Takes a screenshot of an RTSP stream and generates a 24 fps & 60 
fps timelapse, both intervals can be configured via environment 
variables.

# Usage
- Clone the entire repository
  - `git clone https://github.com/Invisi/rtsp-timelapse`
- Configure the environment variables as necessary
  - `editor compose.yml`
- Build the image
  - `docker compose build`
- Run the container
  - `docker compose up -d`
- Wait for it to generate images & videos

# Notes
- Images are deleted whenever generating both timelapses succeeds.
- Generated timelapses are never deleted automatically.
