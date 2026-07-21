"""
轻量 Web 服务 — 零依赖，仅用 Python 内置库。

启动: python web_app.py
访问: http://localhost:8080
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# 使用绝对路径，避免 Render 工作目录问题
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DASHBOARD_FILE = OUTPUT_DIR / "dashboard.html"
RUN_TOKEN = os.getenv("RUN_TOKEN", "")

LANDING_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>高股息分析看板</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
     background:#0f172a;color:#e2e8f0;display:flex;align-items:center;
     justify-content:center;min-height:100vh;margin:0}
.card{background:#1e293b;border:1px solid #334155;border-radius:16px;
      padding:40px 32px;text-align:center;max-width:460px;width:90%}
h1{font-size:1.4rem;margin-bottom:12px}
p{color:#94a3b8;margin-bottom:20px;line-height:1.6;font-size:0.95rem}
button{background:#3b82f6;color:#fff;border:none;padding:14px 36px;
       border-radius:10px;font-size:1rem;cursor:pointer;width:100%}
button:hover{background:#2563eb}
button:disabled{background:#475569;cursor:not-allowed}
input{padding:12px 16px;border-radius:10px;border:1px solid #334155;
      background:rgba(255,255,255,0.06);color:#e2e8f0;width:100%;
      margin-bottom:12px;font-size:0.95rem;outline:none}
input:focus{border-color:#3b82f6}
#status{margin-top:16px;font-size:0.9rem;color:#94a3b8}
.footer{margin-top:24px;color:#64748b;font-size:0.75rem}
</style>
</head>
<body>
<div class="card">
    <h1>📊 高股息分析看板</h1>
    <p>首次使用需先生成数据。<br>点击下方按钮，等待 5-10 分钟即可。</p>
    <input type="password" id="token" placeholder="操作密码（如未设置可留空）">
    <button onclick="run()">🚀 开始首次分析</button>
    <div id="status"></div>
    <div class="footer">分析期间可关闭页面，完成后重新打开即可</div>
</div>
<script>
async function run(){
    const btn=document.querySelector('button');
    btn.disabled=true;
    document.getElementById('status').textContent='⏳ 正在运行，约需 5-10 分钟...';
    try{
        const r=await fetch('/run',{method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({token:document.getElementById('token').value})});
        const d=await r.json();
        if(d.ok){
            document.getElementById('status').innerHTML='✅ 分析完成！<br><a href="/" style="color:#3b82f6">点击查看看板</a>';
        }else{
            document.getElementById('status').textContent='❌ '+d.error;
            btn.disabled=false;
        }
    }catch(e){
        document.getElementById('status').textContent='❌ 网络错误: '+e.message;
        btn.disabled=false;
    }
}
</script>
</body></html>"""


def _read_single_result(code: str) -> dict | None:
    """从最新生成的 Excel 中读取单只股票/ETF 统计。"""
    import pandas as pd

    # 判断是 ETF 还是个股，查对应目录
    is_etf = code.startswith(("15", "51", "58", "56"))
    search_dir = OUTPUT_DIR / ("ETF_batch_analysis" if is_etf else "company_batch_analysis")

    if not search_dir.exists():
        return None

    code_num = code.split(".")[0]
    files = sorted(
        [f for f in search_dir.glob(f"*{code_num}*.xlsx") if "汇总" not in f.name],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not files:
        return None

    try:
        for f in files[:3]:
            try:
                df = pd.read_excel(f, sheet_name="统计指标与标准差")
                data = {}
                for _, row in df.iterrows():
                    k = str(row.iloc[0])
                    v = row.iloc[1]
                    if "均值" in k and "年" in k:
                        data.setdefault("mean", float(str(v).replace("元", "").strip()))
                    elif "最小值" in k:
                        if "3" in k:
                            data["min"] = float(str(v).replace("元", "").strip())
                    elif "临界买点" in k:
                        if "3" in k or "买点" in k:
                            data.setdefault("crit", float(str(v).replace("元", "").strip()))
                    elif "最新收盘价" in k:
                        data["latest"] = float(str(v).replace("元", "").strip())
                    elif "名称" in k:
                        data["name"] = str(v)

                if "latest" in data:
                    latest = data["latest"]
                    crit = data.get("crit", data.get("min", latest) * 1.15)
                    return {
                        "code": code,
                        "name": data.get("name", code),
                        "latest_price": latest,
                        "mean": data.get("mean", latest),
                        "min": data.get("min", latest),
                        "critical_buy_point": crit,
                        "position": "低于" if latest <= crit else "高于",
                        "diff_to_crit": abs(latest - crit),
                    }
            except Exception:
                continue
        return None
    except Exception:
        return None


class DashboardHandler(SimpleHTTPRequestHandler):
    """自定义 HTTP 处理器：静态文件 + API 端点。"""

    def do_GET(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(self.path)
        path = parsed.path

        # API
        if path == "/health":
            self._json({"status": "ok"})
            return

        # 首页
        if path in ("/", "/index.html", "/dashboard.html"):
            if DASHBOARD_FILE.exists():
                self._serve_html(DASHBOARD_FILE)
            else:
                self._serve_landing()
            return

        # 静态文件
        filepath = OUTPUT_DIR / path.lstrip("/")
        if filepath.exists() and filepath.is_file():
            self._serve_html(filepath)
        else:
            self.send_error(404, "File not found")

    def _serve_html(self, filepath: Path):
        """发送 HTML 文件。"""
        content = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_landing(self):
        """显示首次使用引导页。"""
        html = LANDING_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/analyze":
            self._handle_analyze()
        elif parsed.path == "/run":
            self._handle_run()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_analyze(self):
        body = self._read_body()
        code = body.get("code", "").strip()
        if not code:
            self._json({"ok": False, "error": "请输入股票代码"}, 400)
            return

        name = body.get("name", code).strip() or code
        print(f"[analyze] {name} ({code})")

        try:
            subprocess.run(
                [sys.executable, "batch_analysis.py", "--code", code, "--name", name],
                capture_output=True, text=True, timeout=180,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            stats = _read_single_result(code)
            if stats:
                self._json({"ok": True, "code": code, "name": name, "stats": stats})
            else:
                self._json({"ok": False, "error": "分析完成但无法读取结果"})
        except subprocess.TimeoutExpired:
            self._json({"ok": False, "error": "分析超时"}, 500)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)

    def _handle_run(self):
        body = self._read_body()
        if RUN_TOKEN and body.get("token", "") != RUN_TOKEN:
            self._json({"ok": False, "error": "密码错误"}, 403)
            return

        lock = OUTPUT_DIR / ".analysis_running"
        if lock.exists():
            age = (datetime.now() - datetime.fromtimestamp(lock.stat().st_mtime)).total_seconds()
            if age < 1800:
                self._json({"ok": False, "error": f"分析运行中（{int(age)}s 前）"}, 409)
                return

        print("[run] 启动全量分析...")
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            lock.write_text(datetime.now().isoformat())
            subprocess.run(
                [sys.executable, "run_all.py", "--skip-screener"],
                capture_output=True, timeout=900,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            subprocess.run(
                [sys.executable, "generate_dashboard.py"],
                capture_output=True, timeout=60,
            )
            lock.unlink()
            self._json({"ok": True})
        except Exception as e:
            if lock.exists():
                lock.unlink()
            self._json({"ok": False, "error": str(e)}, 500)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[server] {args[0]}")


def main():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"服务已启动: http://localhost:{port}")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == "__main__":
    main()
