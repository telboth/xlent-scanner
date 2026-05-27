"""Minimal PyWebView-test. Kjør med: uv run python test_webview.py"""
import webview

class Api:
    def ping(self):
        return "pong"

html = """
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body>
  <h2 id="status">Venter...</h2>
  <button id="btn">Test API</button>
  <script>
    document.getElementById("status").textContent = "Script kjorer. Poller...";
    let tries = 0;
    const t = setInterval(() => {
      tries++;
      if (window.pywebview && window.pywebview.api) {
        clearInterval(t);
        document.getElementById("status").textContent = "API klar etter " + tries + " forsok!";
      } else if (tries > 100) {
        clearInterval(t);
        document.getElementById("status").textContent = "FEIL: API ikke tilgjengelig. window.pywebview = " + typeof window.pywebview;
      }
    }, 100);

    document.getElementById("btn").onclick = async () => {
      try {
        const r = await window.pywebview.api.ping();
        document.getElementById("status").textContent = "ping-svar: " + r;
      } catch(e) {
        document.getElementById("status").textContent = "Feil: " + e;
      }
    };
  </script>
</body>
</html>
"""

api = Api()
webview.create_window("API-test", html=html, js_api=api, width=500, height=300)
webview.start(debug=True)
