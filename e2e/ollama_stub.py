"""A stand-in for Ollama's /api/chat, so CI can run the full pipeline without model weights.

    python e2e/ollama_stub.py   # listens on :11434

Requests with images get receipt text back (OCR); requests with a JSON schema get fields (extraction).
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TEXT = "KOPI KENANGAN\n12/03/2024\nEs Kopi Susu 2 x 18.000 36.000\nSUBTOTAL 36.000\nTOTAL Rp 36.000"
FIELDS = {
    "merchant_name": "Kopi Kenangan",
    "receipt_date": "2024-03-12",
    "currency": "IDR",
    "subtotal": 36000,
    "tax": None,
    "service_charge": None,
    "discount": None,
    "total": 36000,
    "line_items": [{"description": "Es Kopi Susu", "quantity": 2, "unit_price": 18000, "amount": 36000}],
}


class Stub(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        message = body.get("messages", [{}])[0]
        content = json.dumps(FIELDS) if "format" in body else TEXT if message.get("images") else ""
        payload = json.dumps({"model": body.get("model"), "message": {"role": "assistant", "content": content}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 11434), Stub).serve_forever()
