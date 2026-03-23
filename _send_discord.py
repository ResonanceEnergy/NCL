"""Send Helix News episode to Discord."""

import json
import urllib.request

webhook = "https://discord.com/api/webhooks/1485412527230681270/21GIfjsomScCXlxWTZmK3jwZHH2Ca9ZUy0pjNB2_LbTaCs37-i2Wqdel2StZI20lX8Zl"
ep = 'reports/helix_news/daily_20260322_171625/episode_compressed.mp4'

with open(ep, "rb") as f:
    file_data = f.read()

boundary = b"----HelixBoundary9876"
payload = json.dumps({"content": "**Helix News Daily Brief** \u2014 March 22, 2026 (v4: multi-clip rendering)"}).encode()

body = b""
body += b"--" + boundary + b"\r\n"
body += b'Content-Disposition: form-data; name="payload_json"\r\n\r\n'
body += payload + b"\r\n"
body += b"--" + boundary + b"\r\n"
body += b'Content-Disposition: form-data; name="files[0]"; filename="helix_news_20260322.mp4"\r\n'
body += b"Content-Type: video/mp4\r\n\r\n"
body += file_data + b"\r\n"
body += b"--" + boundary + b"--\r\n"

req = urllib.request.Request(webhook, data=body, method="POST")
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary.decode()}")
req.add_header("User-Agent", "HelixNewsBot/1.0")

resp = urllib.request.urlopen(req)
print(f"Status: {resp.status}")
result = json.loads(resp.read())
print(f"Message ID: {result['id']}")
