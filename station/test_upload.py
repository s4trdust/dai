"""Pretend to be the ESP32 - send photos from disk to the server.

  python station/test_upload.py background empty_board.jpg
  python station/test_upload.py scan piece.jpg 152.3
"""
import json
import sys

import httpx

SERVER = "http://localhost:5000"

mode, path = sys.argv[1], sys.argv[2]
data = open(path, "rb").read()
headers = {"Content-Type": "image/jpeg"}
if mode == "background":
    r = httpx.post(f"{SERVER}/station/background", content=data, headers=headers)
else:
    r = httpx.post(f"{SERVER}/station/scan", params={"weight_g": sys.argv[3]},
                   content=data, headers=headers, timeout=120)
print(r.status_code)
print(json.dumps(r.json(), indent=2))
