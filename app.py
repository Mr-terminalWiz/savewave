from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import re
import threading
import time

# Serve index.html from the same directory as app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')
CORS(app)

@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

DOWNLOAD_DIR = tempfile.mkdtemp()

def is_valid_url(url):
    youtube_regex = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=|shorts/)?([^&=%\?]{11})'
    )
    return bool(youtube_regex.match(url))

def cleanup_file(filepath, delay=120):
    def _cleanup():
        time.sleep(delay)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except:
            pass
    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()

@app.route('/')
def index():
    return send_file(os.path.join(BASE_DIR, 'index.html'))

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    if not is_valid_url(url):
        return jsonify({'error': 'Invalid YouTube URL'}), 400

    ydl_opts = {'quiet': True, 'no_warnings': True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            formats = []
            seen = set()

            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    height = f.get('height')
                    if height and height not in seen:
                        seen.add(height)
                        formats.append({
                            'format_id': f['format_id'],
                            'quality': f'{height}p',
                            'height': height,
                            'ext': f.get('ext', 'mp4'),
                            'filesize': f.get('filesize'),
                        })

            formats.sort(key=lambda x: x['height'], reverse=True)
            formats.append({
                'format_id': 'mp3',
                'quality': 'MP3 Audio',
                'height': 0,
                'ext': 'mp3',
                'filesize': None,
            })

            return jsonify({
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'formats': formats,
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download', methods=['POST'])
def download_video():
    data = request.get_json()
    url = data.get('url', '').strip()
    format_id = data.get('format_id', 'best')
    is_mp3 = format_id == 'mp3'

    if not url or not is_valid_url(url):
        return jsonify({'error': 'Invalid URL'}), 400

    output_path = os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s')

    if is_mp3:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'quiet': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
    else:
        ydl_opts = {
            'format': f'{format_id}+bestaudio/best/{format_id}/best',
            'outtmpl': output_path,
            'quiet': True,
            'merge_output_format': 'mp4',
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')
            ext = 'mp3' if is_mp3 else 'mp4'

            downloaded_file = None
            for f in os.listdir(DOWNLOAD_DIR):
                full_path = os.path.join(DOWNLOAD_DIR, f)
                if os.path.isfile(full_path) and f.endswith(ext):
                    downloaded_file = full_path
                    break

            if not downloaded_file:
                files = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)]
                if files:
                    downloaded_file = max(files, key=os.path.getctime)

            if not downloaded_file or not os.path.exists(downloaded_file):
                return jsonify({'error': 'Download failed'}), 500

            safe_filename = re.sub(r'[^\w\s\-.]', '', title)[:50] + f'.{ext}'
            cleanup_file(downloaded_file)

            return send_file(
                downloaded_file,
                as_attachment=True,
                download_name=safe_filename,
                mimetype='audio/mpeg' if is_mp3 else 'video/mp4'
            )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, port=port, host='0.0.0.0')
