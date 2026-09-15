"""Serveur web local pour convertir des PDF avec pdfexact."""
from __future__ import annotations

import cgi
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path.cwd()
RESULTS_DIR = ROOT / "results" / "web"
UPLOADS_DIR = RESULTS_DIR / "uploads"
OUTPUTS_DIR = RESULTS_DIR / "outputs"
REPORTS_DIR = RESULTS_DIR / "reports"


@dataclass
class Job:
    id: str
    source_name: str
    input_path: Path
    output_path: Path
    report_path: Path
    command: list[str]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "queued"
    returncode: int | None = None
    logs: list[str] = field(default_factory=list)
    error: str = ""


JOBS: dict[str, Job] = {}
LOCK = threading.Lock()


INDEX_HTML = r"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PDFExact - Conversion PDF vers DOCX</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d8dee4;
      --text: #18212b;
      --muted: #687381;
      --brand: #125f73;
      --brand-dark: #0d4d5f;
      --accent: #0f766e;
      --danger: #b42318;
      --ok: #137333;
      --warn: #9a6700;
      --shadow: 0 12px 36px rgba(15, 23, 42, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 28px;
      background: #111827;
      color: white;
      border-bottom: 1px solid #202a3a;
    }
    .brand { display: flex; align-items: center; gap: 12px; font-weight: 760; }
    .mark {
      width: 34px; height: 34px; border-radius: 7px;
      display: grid; place-items: center;
      background: var(--accent);
      color: white;
      font-weight: 900;
    }
    .shell {
      display: grid;
      grid-template-columns: 420px 1fr;
      gap: 18px;
      padding: 18px;
      max-width: 1500px;
      margin: 0 auto;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .panel h2 {
      margin: 0;
      padding: 16px 18px;
      font-size: 15px;
      border-bottom: 1px solid var(--line);
    }
    form { padding: 18px; display: grid; gap: 14px; }
    label { display: grid; gap: 6px; font-size: 12px; font-weight: 700; color: #303946; }
    input, select {
      width: 100%;
      min-height: 38px;
      border: 1px solid #c9d2dc;
      border-radius: 6px;
      padding: 8px 10px;
      background: white;
      color: var(--text);
      font: inherit;
    }
    input[type="checkbox"] { width: 16px; min-height: 16px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .check { display: flex; align-items: center; gap: 9px; font-size: 13px; color: var(--text); }
    .group {
      display: grid;
      gap: 10px;
      padding: 12px;
      border: 1px solid #e1e7ef;
      border-radius: 8px;
      background: #fbfcfe;
    }
    .group-title {
      font-size: 12px;
      font-weight: 800;
      color: #344054;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .drop {
      border: 1px dashed #9fb1c4;
      background: #f7fafb;
      border-radius: 8px;
      padding: 18px;
      display: grid;
      gap: 8px;
    }
    .drop strong { font-size: 14px; }
    .drop span { color: var(--muted); font-size: 12px; }
    button {
      min-height: 42px;
      border: 0;
      border-radius: 6px;
      background: var(--brand);
      color: white;
      font-weight: 760;
      cursor: pointer;
    }
    button:hover { background: var(--brand-dark); }
    button:disabled { background: #98a2b3; cursor: not-allowed; }
    .workspace { display: grid; gap: 18px; align-content: start; }
    .statusbar {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 16px 18px;
      align-items: center;
    }
    .status { font-size: 14px; font-weight: 760; }
    .meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
    .pill {
      padding: 5px 9px;
      border-radius: 999px;
      font-size: 12px;
      background: #e9f5f7;
      color: var(--brand-dark);
      border: 1px solid #b7dce4;
    }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .actions a {
      text-decoration: none;
      color: white;
      background: #334155;
      border-radius: 6px;
      padding: 9px 12px;
      font-size: 13px;
      font-weight: 700;
    }
    pre {
      margin: 0;
      height: calc(100vh - 230px);
      min-height: 440px;
      overflow: auto;
      padding: 14px;
      background: #08111f;
      color: #d7e2f0;
      border-radius: 0 0 8px 8px;
      font: 12px/1.45 "JetBrains Mono", "Roboto Mono", monospace;
      white-space: pre-wrap;
    }
    .empty {
      padding: 54px 18px;
      text-align: center;
      color: var(--muted);
    }
    .tabs {
      display: flex;
      gap: 6px;
      padding: 12px 18px 0;
      border-bottom: 1px solid var(--line);
    }
    .report {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 0 18px 16px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: #fbfcfe;
    }
    .metric span { display: block; color: var(--muted); font-size: 11px; }
    .metric strong { display: block; margin-top: 4px; font-size: 16px; }
    .tab {
      padding: 9px 12px;
      border-radius: 6px 6px 0 0;
      border: 1px solid var(--line);
      border-bottom: 0;
      background: white;
      font-size: 13px;
      font-weight: 760;
    }
    @media (max-width: 980px) {
      .shell { grid-template-columns: 1fr; }
      pre { height: 420px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand"><div class="mark">PX</div><div>PDFExact Studio</div></div>
    <div class="pill">Local</div>
  </header>

  <main class="shell">
    <section class="panel">
      <h2>Nouvelle conversion</h2>
      <form id="convertForm">
        <label class="drop">
          <strong>PDF source</strong>
          <span>Document PDF natif ou complexe</span>
          <input id="pdf" name="pdf" type="file" accept="application/pdf" required>
        </label>

        <div class="row">
          <label>DPI
            <input name="dpi" type="number" value="100" min="72" max="600">
          </label>
          <label>DPI audit
            <input name="final_audit_dpi" type="number" value="100" min="72" max="300">
          </label>
        </div>

        <div class="row">
          <label>Pages
            <input name="pages" placeholder="ex: 1-5,8">
          </label>
          <label>Device IA
            <select name="layout_device">
              <option value="cpu" selected>CPU</option>
              <option value="gpu">GPU</option>
            </select>
          </label>
        </div>

        <div class="row">
          <label>Texte
            <select name="text_mode">
              <option value="rapidocr" selected>RapidOCR</option>
              <option value="spans">PDF natif</option>
              <option value="glyph-images">Glyph images</option>
            </select>
          </label>
          <label>Layout
            <select name="ocr_layout">
              <option value="word-native" selected>Word native exact</option>
              <option value="hybrid">Hybrid</option>
              <option value="blocks">Blocks</option>
            </select>
          </label>
        </div>

        <label>OCR granularite
          <select name="ocr_granularity">
            <option value="line" selected>Line</option>
            <option value="word">Word</option>
            <option value="char">Char</option>
          </select>
        </label>

        <div class="group">
          <div class="group-title">Polices</div>
          <label>Dossier polices
            <input name="font_dir" value="fonts/local">
          </label>
          <label class="check"><input name="fetch_missing_fonts" type="checkbox" checked> Chercher les polices libres manquantes</label>
        </div>

        <div class="group">
          <div class="group-title">IA documentaire</div>
          <label>Racine modeles IA
            <input name="layout_model_root" value="/home/raphael/Mes_Projets/vysi/ai_models">
          </label>

          <label>Modele layout
            <input name="layout_model" value="ppstructurev3/PP-DocLayout_plus-L">
          </label>

          <label class="check"><input name="layout_ai" type="checkbox" checked> Activer Layout IA PaddleX</label>
          <label class="check"><input name="final_audit" type="checkbox" checked> Audit final et recuperation avant livraison</label>
        </div>

        <button id="submitBtn" type="submit">Convertir en DOCX</button>
      </form>
    </section>

    <section class="workspace">
      <div class="panel">
        <div class="statusbar">
          <div>
            <div id="status" class="status">Aucune conversion lancee</div>
            <div id="meta" class="meta">Charge un PDF puis lance la conversion.</div>
          </div>
          <div id="actions" class="actions"></div>
        </div>
        <div id="report" class="report"></div>
      </div>

      <div class="panel">
        <div class="tabs"><div class="tab">Journal</div></div>
        <pre id="logs">En attente.</pre>
      </div>
    </section>
  </main>

  <script>
    const form = document.getElementById('convertForm');
    const submitBtn = document.getElementById('submitBtn');
    const statusEl = document.getElementById('status');
    const metaEl = document.getElementById('meta');
    const logsEl = document.getElementById('logs');
    const actionsEl = document.getElementById('actions');
    const reportEl = document.getElementById('report');
    let currentJob = null;
    let timer = null;

    function setStatus(job) {
      const label = {
        queued: 'En file',
        running: 'Conversion en cours',
        succeeded: 'Conversion terminee',
        failed: 'Conversion echouee'
      }[job.status] || job.status;
      statusEl.textContent = label;
      metaEl.textContent = job.source_name + ' | job ' + job.id;
      logsEl.textContent = (job.logs || []).join('');
      logsEl.scrollTop = logsEl.scrollHeight;
      actionsEl.innerHTML = '';
      renderReport(job.report_summary || null);
      if (job.status === 'succeeded') {
        actionsEl.innerHTML =
          '<a href="/api/jobs/' + job.id + '/download/docx">DOCX</a>' +
          '<a href="/api/jobs/' + job.id + '/download/report">Rapport JSON</a>';
      }
      if (job.status === 'failed' && job.error) {
        logsEl.textContent += '\nERREUR: ' + job.error;
      }
      submitBtn.disabled = job.status === 'queued' || job.status === 'running';
    }

    function renderReport(report) {
      reportEl.innerHTML = '';
      if (!report) return;
      const cert = report.certification_finale || {};
      const items = [
        ['Pages', report.pages_totales ?? '-'],
        ['Images', report.images ?? '-'],
        ['Audit', cert.active ? (cert.conforme ? 'OK' : 'A revoir') : '-'],
        ['Score visuel', cert.score_visuel_min == null ? '-' : cert.score_visuel_min.toFixed(3)],
        ['Ratio texte', cert.ratio_texte == null ? '-' : cert.ratio_texte.toFixed(3)],
        ['Recuperations', cert.zones_visuelles_recuperees ?? 0],
        ['Manques', cert.zones_visuelles_non_couvertes ?? 0],
        ['Fonts proches', (report.polices_substituees || []).length]
      ];
      reportEl.innerHTML = items.map(([k, v]) =>
        '<div class="metric"><span>' + k + '</span><strong>' + v + '</strong></div>'
      ).join('');
    }

    async function poll() {
      if (!currentJob) return;
      const res = await fetch('/api/jobs/' + currentJob);
      const job = await res.json();
      setStatus(job);
      if (job.status === 'succeeded' || job.status === 'failed') {
        clearInterval(timer);
        timer = null;
      }
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      submitBtn.disabled = true;
      logsEl.textContent = 'Upload...\n';
      actionsEl.innerHTML = '';
      const data = new FormData(form);
      const res = await fetch('/api/jobs', { method: 'POST', body: data });
      if (!res.ok) {
        logsEl.textContent = await res.text();
        submitBtn.disabled = false;
        return;
      }
      const job = await res.json();
      currentJob = job.id;
      setStatus(job);
      if (timer) clearInterval(timer);
      timer = setInterval(poll, 1000);
      poll();
    });
  </script>
</body>
</html>
"""


def _safe_name(name: str) -> str:
    base = Path(name or "document.pdf").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base or "document.pdf"


def _json_job(job: Job) -> dict:
    report_summary = None
    if job.report_path.exists():
        try:
            report_summary = json.loads(job.report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report_summary = None
    return {
        "id": job.id,
        "source_name": job.source_name,
        "status": job.status,
        "returncode": job.returncode,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "logs": job.logs[-1200:],
        "error": job.error,
        "has_docx": job.output_path.exists(),
        "has_report": job.report_path.exists(),
        "report_summary": report_summary,
    }


def _field(form: cgi.FieldStorage, name: str, default: str = "") -> str:
    item = form[name] if name in form else None
    if item is None or getattr(item, "filename", None):
        return default
    value = item.value
    return value if value is not None else default


def _checked(form: cgi.FieldStorage, name: str) -> bool:
    return name in form and str(form[name].value).lower() not in {"0", "false", "off", ""}


def _build_command(form: cgi.FieldStorage, input_path: Path, output_path: Path, report_path: Path) -> list[str]:
    dpi = _field(form, "dpi", "100").strip() or "100"
    text_mode = _field(form, "text_mode", "rapidocr").strip() or "rapidocr"
    ocr_layout = _field(form, "ocr_layout", "word-native").strip() or "word-native"
    ocr_granularity = _field(form, "ocr_granularity", "line").strip() or "line"
    font_dir = _field(form, "font_dir", "fonts/local").strip() or "fonts/local"
    layout_model_root = _field(form, "layout_model_root", "").strip()
    layout_model = _field(form, "layout_model", "").strip()
    layout_device = _field(form, "layout_device", "cpu").strip() or "cpu"
    final_audit_dpi = _field(form, "final_audit_dpi", "100").strip() or "100"
    pages = _field(form, "pages", "").strip()

    cmd = [
        sys.executable,
        "-m",
        "pdfexact.cli",
        str(input_path),
        str(output_path),
        "--text-mode",
        text_mode,
        "--ocr-layout",
        ocr_layout,
        "--ocr-granularity",
        ocr_granularity,
        "--dpi",
        dpi,
        "--font-dir",
        font_dir,
        "--font-cache-dir",
        font_dir,
        "--report",
        str(report_path),
        "--verbose",
    ]
    if pages:
        cmd.extend(["--pages", pages])
    if _checked(form, "fetch_missing_fonts"):
        cmd.append("--fetch-missing-fonts")
    if _checked(form, "layout_ai"):
        cmd.extend(["--layout-ai", "--layout-provider", "paddlex"])
        if layout_model:
            cmd.extend(["--layout-model", layout_model])
        if layout_model_root:
            cmd.extend(["--layout-model-root", layout_model_root])
        if layout_device:
            cmd.extend(["--layout-device", layout_device])
    if _checked(form, "final_audit"):
        cmd.extend(["--final-audit", "--final-audit-dpi", final_audit_dpi])
    return cmd


def _run_job(job_id: str) -> None:
    with LOCK:
        job = JOBS[job_id]
        job.status = "running"
        job.updated_at = time.time()
    env = os.environ.copy()
    env.setdefault("DISABLE_MODEL_SOURCE_CHECK", "1")
    try:
        process = subprocess.Popen(
            job.command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            with LOCK:
                job.logs.append(line)
                job.updated_at = time.time()
        returncode = process.wait()
        with LOCK:
            job.returncode = returncode
            job.status = "succeeded" if returncode == 0 and job.output_path.exists() else "failed"
            if job.status == "failed":
                job.error = f"process exited with code {returncode}"
            job.updated_at = time.time()
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            job.status = "failed"
            job.error = str(exc)
            job.updated_at = time.time()


class Handler(BaseHTTPRequestHandler):
    server_version = "PDFExactWeb/0.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send(HTTPStatus.OK, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
            job_id = parts[2]
            with LOCK:
                job = JOBS.get(job_id)
                data = _json_job(job) if job else None
            if data is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "job introuvable"})
            else:
                self._json(HTTPStatus.OK, data)
            return
        if len(parts) == 5 and parts[:2] == ["api", "jobs"] and parts[3] == "download":
            self._download(parts[2], parts[4])
            return
        self._send(HTTPStatus.NOT_FOUND, b"not found")

    def _download(self, job_id: str, kind: str) -> None:
        with LOCK:
            job = JOBS.get(job_id)
        if job is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "job introuvable"})
            return
        path = job.output_path if kind == "docx" else job.report_path if kind == "report" else None
        if path is None or not path.exists():
            self._json(HTTPStatus.NOT_FOUND, {"error": "fichier introuvable"})
            return
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if kind == "docx"
            else "application/json"
        )
        filename = path.name
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/jobs":
            self._send(HTTPStatus.NOT_FOUND, b"not found")
            return
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self._send(HTTPStatus.BAD_REQUEST, b"multipart/form-data requis")
            return
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": ctype,
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        file_item = form["pdf"] if "pdf" in form else None
        if file_item is None or not file_item.file:
            self._send(HTTPStatus.BAD_REQUEST, b"PDF manquant")
            return

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        job_id = uuid.uuid4().hex[:12]
        source_name = _safe_name(file_item.filename or "document.pdf")
        stem = Path(source_name).stem
        input_path = UPLOADS_DIR / f"{job_id}_{source_name}"
        output_path = OUTPUTS_DIR / f"{job_id}_{stem}.docx"
        report_path = REPORTS_DIR / f"{job_id}_{stem}.json"
        with input_path.open("wb") as handle:
            while True:
                chunk = file_item.file.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)

        command = _build_command(form, input_path, output_path, report_path)
        job = Job(job_id, source_name, input_path, output_path, report_path, command)
        job.logs.append("$ " + " ".join(command) + "\n")
        with LOCK:
            JOBS[job_id] = job
        threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
        self._json(HTTPStatus.CREATED, _json_job(job))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interface web locale PDFExact.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    host = args.host
    port = args.port
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"PDFExact Studio: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
