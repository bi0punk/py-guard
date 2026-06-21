import os
import uuid
from pathlib import Path
from typing import List

from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from parser import LogAnalyzer, load_summary, save_summary


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / 'uploads'
DATA_DIR = BASE_DIR / 'data'
ALLOWED_EXTENSIONS = {'.log', '.txt'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

UPLOAD_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or os.urandom(24).hex()


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    recent_reports = []
    for path in sorted(DATA_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
        recent_reports.append({'analysis_id': path.stem, 'filename': path.name})
    return render_template('index.html', recent_reports=recent_reports)


@app.route('/analyze', methods=['POST'])
def analyze():
    files = request.files.getlist('log_files')
    saved_paths: List[str] = []

    if not files or all(not f.filename for f in files):
        return render_template('index.html', error='Debes subir al menos un archivo .log o .txt', recent_reports=[]), 400

    for file in files:
        if not file.filename:
            continue
        if not allowed_file(file.filename):
            return render_template(
                'index.html',
                error=f'Archivo no soportado: {file.filename}. Usa .log o .txt',
                recent_reports=[],
            ), 400

        safe_name = secure_filename(file.filename)
        unique_name = f'{uuid.uuid4()}_{safe_name}'
        destination = UPLOAD_DIR / unique_name
        file.save(destination)
        saved_paths.append(str(destination))

    analyzer = LogAnalyzer()
    result = analyzer.parse_files(saved_paths)
    save_summary(str(DATA_DIR), result)

    return redirect(url_for('report', analysis_id=result['analysis_id']))


@app.route('/report/<analysis_id>')
def report(analysis_id: str):
    data = load_summary(str(DATA_DIR), analysis_id)
    if not data:
        return render_template('404.html'), 404
    return render_template('report.html', data=data)


@app.route('/api/report/<analysis_id>')
def api_report(analysis_id: str):
    data = load_summary(str(DATA_DIR), analysis_id)
    if not data:
        return jsonify({'error': 'analysis not found'}), 404
    return jsonify(data)


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8000'))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'
    app.run(host=host, port=port, debug=debug)
