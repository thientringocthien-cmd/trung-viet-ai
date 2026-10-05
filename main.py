import os
import re
import uuid
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, FileResponse
from deep_translator import GoogleTranslator
from gtts import gTTS
import yt_dlp
import imageio_ffmpeg

BASE = Path("/tmp/trung_viet_ai")
BASE.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="TRUNG → VIỆT AI")

HTML = """
<!doctype html>
<html lang="vi">
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TRUNG → VIỆT AI</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,Arial;margin:0;background:#f4f7fb;color:#172033}
.box{max-width:720px;margin:40px auto;padding:24px;background:white;border-radius:22px;box-shadow:0 8px 30px #0001}
h1{font-size:30px;margin:0 0 8px} .sub{color:#667085;margin-bottom:24px}
input{width:100%;box-sizing:border-box;padding:16px;border:1px solid #ccd3df;border-radius:12px;font-size:16px}
button{width:100%;padding:16px;margin-top:14px;border:0;border-radius:12px;background:#1769e0;color:white;font-size:17px;font-weight:700}
.note{margin-top:18px;padding:14px;background:#eef5ff;border-radius:12px;font-size:14px}
.err{background:#fff0f0;color:#b42318;padding:14px;border-radius:12px;margin-top:16px}
.ok{background:#ecfdf3;color:#067647;padding:14px;border-radius:12px;margin-top:16px}
a{display:block;text-align:center;margin-top:12px;padding:14px;background:#111827;color:white;border-radius:12px;text-decoration:none}
</style>
</head>
<body>
<div class="box">
<h1>🇨🇳 TRUNG → VIỆT AI 🇻🇳</h1>
<div class="sub">Dịch nội dung YouTube tiếng Trung sang tiếng Việt và tạo giọng đọc tiếng Việt.</div>
<form method="post" action="/translate">
<input name="url" type="url" required placeholder="Dán link YouTube tại đây">
<button type="submit">🚀 DỊCH & TẠO GIỌNG VIỆT</button>
</form>
<div class="note">Bản miễn phí ưu tiên video có phụ đề tiếng Trung. Video quá dài hoặc không có phụ đề có thể cần xử lý riêng.</div>
</div>
</body>
</html>
"""

def clean_text(s):
    s = re.sub(r"\[[0-9:.]+ --> [0-9:.]+\]", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
    return re.sub(r"\s+", " ", s).strip()

def parse_vtt(path):
    text = Path(path).read_text(errors="ignore")
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        if "-->" in line or re.fullmatch(r"\d+", line):
            continue
        line = clean_text(line)
        if line:
            lines.append(line)
    # remove consecutive duplicate subtitle lines
    out = []
    for x in lines:
        if not out or x != out[-1]:
            out.append(x)
    return " ".join(out)

def get_subtitle(url, work):
    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["zh-Hans", "zh", "zh-CN", "zh-TW"],
        "subtitlesformat": "vtt",
        "outtmpl": str(work / "source.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    files = list(work.glob("source*.vtt"))
    if not files:
        raise RuntimeError("Không tìm thấy phụ đề tiếng Trung. Hãy thử video có phụ đề Trung.")
    return parse_vtt(files[0])

def translate_text(text):
    # Translate in chunks to avoid oversized requests.
    chunks = []
    words = text.split()
    buf = ""
    for w in words:
        if len(buf) + len(w) + 1 > 3500:
            chunks.append(buf)
            buf = w
        else:
            buf = (buf + " " + w).strip()
    if buf:
        chunks.append(buf)
    tr = GoogleTranslator(source="zh-CN", target="vi")
    return "\n".join(tr.translate(c) for c in chunks)

def make_voice(text, work):
    # gTTS handles Vietnamese and creates MP3 without an API key.
    out = work / "vietnamese.mp3"
    gTTS(text=text[:4500], lang="vi").save(str(out))
    return out

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(HTML)

@app.post("/translate", response_class=HTMLResponse)
def translate(url: str = Form(...)):
    work = BASE / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)
    try:
        parsed = urlparse(url)
        if parsed.netloc not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
            raise RuntimeError("Vui lòng nhập link YouTube.")
        zh = get_subtitle(url, work)
        if not zh:
            raise RuntimeError("Phụ đề tiếng Trung trống.")
        vi = translate_text(zh)
        voice = make_voice(vi, work)
        (work / "translation.txt").write_text(vi, encoding="utf-8")
        token = work.name
        return HTMLResponse(f"""
        <div class="box">
        <h1>✅ Đã xử lý</h1>
        <div class="ok">Đã dịch từ tiếng Trung sang tiếng Việt và tạo giọng đọc.</div>
        <a href="/download/{token}/translation">📄 Tải bản dịch tiếng Việt</a>
        <a href="/download/{token}/voice">🔊 Tải giọng Việt MP3</a>
        <p style="margin-top:20px;color:#667085">Lưu ý: bản miễn phí hiện tạo giọng Việt riêng. Ghép giọng vào video cần bước xử lý video tiếp theo.</p>
        <a href="/">← Dịch video khác</a>
        </div>
        """)
    except Exception as e:
        return HTMLResponse(f"""
        <div class="box"><h1>⚠️ Không xử lý được</h1>
        <div class="err">{clean_text(str(e))}</div>
        <a href="/">← Thử lại</a></div>
        """, status_code=400)
    finally:
        # Files remain in /tmp for download during the instance lifetime.
        pass

@app.get("/download/{token}/{kind}")
def download(token: str, kind: str):
    work = BASE / token
    if kind == "translation":
        path, name = work / "translation.txt", "ban-dich-tieng-viet.txt"
    elif kind == "voice":
        path, name = work / "vietnamese.mp3", "giong-viet.mp3"
    else:
        return {"error": "invalid file"}
    if not path.exists():
        return {"error": "file expired"}
    return FileResponse(path, filename=name)

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
