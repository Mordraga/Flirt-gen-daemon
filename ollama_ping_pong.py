import requests

payload = {
    "model": "dolphin3:8b",
    "prompt": "Respond with pong when active",
}

r = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=60)
print(r.status_code)
print(r.text)
