# Re:Source + scanning station

A Flask website for the school scrapyard library, plus an ESP32-S3 scanning station.
The station weighs and photographs a piece. The website measures it with OpenCV,
identifies it with Gemini, and either:
- **counts it into a storage section**: 1 Acrylic offcuts, 2 Cardboard, 3 Wires, 4 PLA.
  Only the quantity of that section's library item goes up.
- **sends it to the manual area (0)**: too large, other materials, or the AI is unsure.
  The piece becomes its own library item with size, weight, photo, AI notes and a QR label.

The **Register** page takes a photo uploaded from the device; Gemini identifies it and fills
in the form for you to check. "Fill in by hand instead" skips the AI. Sizes from a photo are
only estimates, so check them.
For the weight, put the item on the station's scale and press "Get weight from scale". Only
then does the website ask the ESP32 for a reading (`GET http://<ESP32 IP>/weight`). The website
remembers the ESP32's IP from the photos it sends (saved in `station/station_ip.txt`), or you
can set it with `setx STATION_URL http://<ESP32 IP>`. While a Register page is open, the
station does not sort pieces put on the scale (the flap does not move).

```
app.py, database.py, templates/, static/   the website (database.db)
station/config.py         sections, size limits, board/marker settings
station/measure.py        ArUco + OpenCV dimension measurement
station/classify.py       Gemini classification (fixed answer lists)
station/make_markers.py   printable corner markers
station/test_upload.py    send photos from disk without the ESP32
firmware/scrap_scanner/   ESP32-S3 Arduino sketch
```

## Setup

1. `pip install -r requirements.txt`
2. Get a free Gemini API key at https://aistudio.google.com/apikey, then
   `setx GEMINI_API_KEY your-key` and open a new terminal.
3. `python app.py`. The website is on http://localhost:5000 and the ESP32 reaches it at
   http://<this PC's IP>:5000. Find the IP with `ipconfig`.
4. **Markers**: `python -m station.make_markers`, print `markers_A4.png` at 100% scale, and tape
   marker 0 top-left, 1 top-right, 2 bottom-right, 3 bottom-left of the grid. Measure the
   centre-to-centre distances and set `MARKER_SPAN_X_CM` / `MARKER_SPAN_Y_CM` in
   `station/config.py`.
5. **Firmware**: install the libraries listed at the top of the sketch, copy
   `wifi_secrets.example.h` to `wifi_secrets.h` and fill in your WiFi (that file is not committed), set
   `SERVER_URL`, set `SECTION_ANGLES` to your flap positions, and upload.
6. **Scale calibration**: in Serial Monitor with the scale empty, send `t`. Put a known weight
   on (e.g. 500 g), send `c`, and set `SCALE_FACTOR = printed value / 500`.
7. Power on with the board **empty**; the station sends the empty-board photo itself.
   Send `b` whenever the lighting changes.

To change what each section holds, or the size limit for sections, edit `station/config.py`.
