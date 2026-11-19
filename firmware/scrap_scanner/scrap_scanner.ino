// Scrap scanner firmware - ESP32 + HX711 load cell (+ optional camera and servo flap)
//
// USE_CAMERA 0 (default): scale + flap, driven by the website. The weight is printed in the
//   Serial Monitor, and the website's Register page reads it with its "Get weight from scale"
//   button (GET http://<this IP>/weight). When a small item is deposited on the Register page,
//   the website turns the flap to its section (GET http://<this IP>/flap?section=4).
//   Board: any ESP32 (e.g. "ESP32 Dev Module").
//   Libraries: "HX711" by Bogdan Necula, "ESP32Servo" by Kevin Harrington.
//
// USE_CAMERA 1: full sorting station (Freenove ESP32-S3 WROOM CAM). Wait for a stable weight ->
//   take photo -> POST to the website -> move flap to the returned section -> wait until the
//   piece is removed -> repeat.
//   Board "ESP32S3 Dev Module", PSRAM "OPI PSRAM". Extra libraries: "ArduinoJson" by
//   Benoit Blanchon, "ESP32Servo" by Kevin Harrington.
//
// Serial Monitor at 115200 baud. Commands:
//   t = tare (zero) the scale - take everything off it first
//   c = print raw reading for calibration
//   p = pause / resume the weight printout
//   0-4 = turn the flap to the manual area (0) or section 1-4, to test the servo angles
//   a / d = nudge the flap 5 degrees either way (to line it up again after drift)
//   r = spin one full circle, to calibrate MS_PER_DEGREE for the 360-degree servo
//   q = spin a quarter circle, to calibrate START_MS (short moves)
//   w = four quarter turns in a row - should add up to one full circle
//   b = resend empty-board photo (camera only)

#define USE_CAMERA 0

#include <WiFi.h>
#include <WebServer.h>
#include "HX711.h"
#include <ESP32Servo.h>
#if USE_CAMERA
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_camera.h"
#endif

// ---------------- Settings to edit ----------------
#include "wifi_secrets.h"   // WiFi name + password: copy wifi_secrets.example.h to wifi_secrets.h
const char* WIFI_SSID   = WIFI_SSID_VALUE;
const char* WIFI_PASS   = WIFI_PASS_VALUE;
const char* SERVER_URL  = "http://192.168.1.50:5000";  // IP of the PC running the website

const int   HX711_DT_PIN  = 5;
const int   HX711_SCK_PIN = 4;
#if USE_CAMERA
#error "GPIO 4 and 5 are camera pins on the Freenove board - move the HX711 before enabling the camera"
#endif
float       SCALE_FACTOR  = 311.9f;   // raw units per gram - see calibration in README

const float STABLE_RANGE_G = 0.5f;    // max wobble between readings to count as settled
const int   STABLE_SAMPLES = 8;
const unsigned long WIFI_WAIT_MS = 20000;  // give up waiting for WiFi at boot after this

const int   SERVO_PIN = 7;            // servo signal wire (orange/yellow); GPIO 7 is a camera
                                      // pin on the Freenove board, so move it if USE_CAMERA is 1
// Funnel angle per destination: index 0 = manual area, 1-4 = storage sections 1-4
// (what each section holds is set on the website side in station/config.py).
// The four boxes sit around the servo, a quarter turn apart. The manual area has no box
// (-1), so the funnel stays where it is and the item is taken off by hand.
const int   SECTION_ANGLES[5] = {-1, 0, 90, 180, 270};
const int   MANUAL_AREA = 0;          // also used if the website can't be reached

// 360-degree (continuous rotation) servo: it cannot go to an angle, only spin. The flap is
// moved by spinning for a measured time, and the sketch remembers where the flap should be.
// Point the funnel at SECTION 1 before powering on - that is where it assumes it starts.
const int   SPIN_US       = 200;      // spin speed: pulse is 1500 us +/- this (max 1000)
float       MS_PER_DEGREE = 5.15f;  // calibrate with the 'r' command (see below)
int         START_MS      = 14;     // extra time per move while the servo gets up to speed;
                                      // raise it if short moves (section to section) fall short

#if USE_CAMERA
const float PRESENT_G = 5.0f;         // above this, a piece is on the scale
const float EMPTY_G   = 2.0f;         // below this, the scale is empty again

// ---------------- Camera pins (Freenove ESP32-S3 WROOM CAM / ESP32-S3-EYE) ----------------
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  15
#define SIOD_GPIO_NUM   4
#define SIOC_GPIO_NUM   5
#define Y9_GPIO_NUM    16
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
#define Y6_GPIO_NUM    12
#define Y5_GPIO_NUM    10
#define Y4_GPIO_NUM     8
#define Y3_GPIO_NUM     9
#define Y2_GPIO_NUM    11
#define VSYNC_GPIO_NUM  6
#define HREF_GPIO_NUM   7
#define PCLK_GPIO_NUM  13
#endif

HX711 scale;
WebServer web(80);   // answers the website's weight requests
bool printWeight = true;

// Returns true and sets `grams` when STABLE_SAMPLES readings agree within STABLE_RANGE_G.
bool readStableWeight(float& grams) {
  float lo = 1e9, hi = -1e9, sum = 0;
  for (int i = 0; i < STABLE_SAMPLES; i++) {
    float g = scale.get_units(1);
    lo = min(lo, g);
    hi = max(hi, g);
    sum += g;
  }
  grams = sum / STABLE_SAMPLES;
  return (hi - lo) <= STABLE_RANGE_G;
}

// GET /weight - asked by the website only when "Get weight from scale" is pressed on the
// Register page. Takes one fresh reading and replies {"g": 152.3, "stable": true}.
void handleWeightRequest() {
  float grams;
  bool stable = readStableWeight(grams);
  web.send(200, "application/json",
           "{\"g\":" + String(grams, 1) + ",\"stable\":" + (stable ? "true" : "false") + "}");
  Serial.printf("Weight sent to the website: %.1f g%s\n", grams, stable ? "" : " (not settled)");
}

Servo flap;
int flapAngle = SECTION_ANGLES[1];   // where the funnel is believed to point (0-359)

// Spin the servo by roughly `degrees` (negative = the other way), then stop. The servo only
// gets pulses while spinning, so it cannot creep or run away while idle.
void spin(float degrees) {
  if (fabs(degrees) < 1) return;
  flap.attach(SERVO_PIN, 500, 2500);
  flap.writeMicroseconds(1500 + (degrees > 0 ? SPIN_US : -SPIN_US));
  delay(START_MS + (unsigned long)(fabs(degrees) * MS_PER_DEGREE));
  flap.writeMicroseconds(1500);
  delay(50);
  flap.detach();
}

void moveFlap(int section) {
  if (section < 0 || section > 4) section = MANUAL_AREA;
  int target = SECTION_ANGLES[section];
  if (target < 0) {                   // no box for this destination: leave the funnel alone
    Serial.println("Manual area: funnel not moved, take the item off by hand");
    return;
  }
  int turn = ((target - flapAngle) % 360 + 360) % 360;   // 0..359 the positive way round
  if (turn > 180) turn -= 360;                            // shorter to go the other way
  spin(turn);
  flapAngle = target;
  if (section == MANUAL_AREA) Serial.println("Flap -> manual area");
  else Serial.printf("Flap -> section %d\n", section);
}

// GET /flap?section=N - sent by the website when an item is deposited on the Register page.
// N is 0 (manual area) or 1-4. Replies {"ok": true, "section": N}.
void handleFlapRequest() {
  int section = web.hasArg("section") ? web.arg("section").toInt() : -1;
  if (section < 0 || section > 4) {
    web.send(400, "application/json", "{\"ok\":false,\"error\":\"section must be 0-4\"}");
    return;
  }
  Serial.printf("Website: deposit -> ");
  moveFlap(section);
  web.send(200, "application/json", "{\"ok\":true,\"section\":" + String(section) + "}");
}

#if USE_CAMERA
enum State { WAIT_FOR_PIECE, WAIT_FOR_REMOVAL };
State state = WAIT_FOR_PIECE;

bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;  c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_QXGA;        // 2048x1536 (3MP)
  c.jpeg_quality = 10;                  // lower = better quality, bigger file
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;

  if (esp_camera_init(&c) != ESP_OK) return false;

  sensor_t* s = esp_camera_sensor_get();
  if (s->id.PID != OV3660_PID) {
    s->set_framesize(s, FRAMESIZE_UXGA);  // OV2640 is 2MP max
  }
  // Let auto exposure / white balance settle, then lock them so colours are
  // consistent from one photo to the next.
  for (int i = 0; i < 15; i++) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
    delay(100);
  }
  s->set_whitebal(s, 0);
  s->set_exposure_ctrl(s, 0);
  s->set_gain_ctrl(s, 0);
  return true;
}

camera_fb_t* takePhoto() {
  // Throw away buffered frames so the photo is taken now, not before the piece arrived.
  for (int i = 0; i < 2; i++) {
    camera_fb_t* old = esp_camera_fb_get();
    if (old) esp_camera_fb_return(old);
  }
  return esp_camera_fb_get();
}

// POSTs the photo; returns the HTTP status (negative on connection failure).
int postPhoto(const String& path, camera_fb_t* fb, String& response) {
  HTTPClient http;
  http.begin(String(SERVER_URL) + path);
  http.addHeader("Content-Type", "image/jpeg");
  http.setTimeout(120000);  // AI classification can take tens of seconds
  int code = http.POST(fb->buf, fb->len);
  response = code > 0 ? http.getString() : http.errorToString(code);
  http.end();
  return code;
}

void sendBackground() {
  Serial.println("Sending empty-board photo...");
  camera_fb_t* fb = takePhoto();
  if (!fb) { Serial.println("Camera capture failed"); return; }
  String response;
  int code = postPhoto("/station/background", fb, response);
  esp_camera_fb_return(fb);
  Serial.printf("Background: HTTP %d %s\n", code, response.c_str());
}

void scanPiece(float grams) {
  Serial.printf("Piece detected: %.1f g\n", grams);
  camera_fb_t* fb = takePhoto();
  if (!fb) { Serial.println("Camera capture failed"); moveFlap(MANUAL_AREA); return; }

  String response;
  int code = postPhoto("/station/scan?weight_g=" + String(grams, 1), fb, response);
  esp_camera_fb_return(fb);

  if (code != 200) {
    Serial.printf("Server error: HTTP %d %s\n", code, response.c_str());
    moveFlap(MANUAL_AREA);
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, response)) {
    Serial.println("Could not parse server reply");
    moveFlap(MANUAL_AREA);
    return;
  }
  if (doc["hold"] | false) {
    // Someone is weighing this item on the website's Register page: don't sort it.
    Serial.println("Register page open - not sorting, take the item off when done");
    return;
  }
  Serial.printf("Item %ld: %s (quantity now %d)\n", doc["item_id"].as<long>(),
                doc["name"] | "?", doc["quantity"] | 1);
  moveFlap(doc["section"] | MANUAL_AREA);
}
#endif

void handleSerial() {
  if (!Serial.available()) return;
  char cmd = Serial.read();
  if (cmd == 't') {
    Serial.println("Taring... keep the scale empty and still");
    scale.tare(20);
    Serial.println("Tared: the scale now reads 0 g");
  }
  if (cmd == 'c') {
    // Put a known weight on, then SCALE_FACTOR = printed value / known grams.
    Serial.printf("Raw (tared) reading: %.1f\n", scale.get_value(20));
  }
  if (cmd == 'p') {
    printWeight = !printWeight;
    Serial.println(printWeight ? "Weight printout on" : "Weight printout paused (p to resume)");
  }
  if (cmd >= '0' && cmd <= '4') moveFlap(cmd - '0');
  // Nudge the flap 5 degrees without changing where the sketch thinks it is: use these to
  // line it up again when it has drifted.
  if (cmd == 'a') { spin(-5); Serial.println("Nudged -5"); }
  if (cmd == 'd') { spin(5);  Serial.println("Nudged +5"); }
  if (cmd == 'r') {
    // Calibration: should turn exactly one full circle. Less -> raise MS_PER_DEGREE, more -> lower it.
    Serial.printf("Spinning 360 degrees (MS_PER_DEGREE = %.2f)...\n", MS_PER_DEGREE);
    spin(360);
    Serial.println("Done. Full circle? If not, MS_PER_DEGREE = current x 360 / degrees it turned");
  }
  if (cmd == 'q') {
    // Calibration for short moves: should turn exactly a quarter circle. Less -> raise START_MS.
    Serial.printf("Spinning 90 degrees (START_MS = %d)...\n", START_MS);
    spin(90);
    Serial.println("Done. Quarter circle? If short, raise START_MS; if too far, lower it");
  }
  if (cmd == 'w') {
    // Calibration: four quarter turns in a row (like going round the boxes). Compare with 'r'.
    Serial.printf("4 x 90 degrees (MS_PER_DEGREE = %.2f, START_MS = %d)...\n", MS_PER_DEGREE, START_MS);
    for (int i = 0; i < 4; i++) { spin(90); delay(300); }
    Serial.println("Done. How far did it turn in total?");
  }
#if USE_CAMERA
  if (cmd == 'b') sendBackground();
#endif
}

// Prints the IP once WiFi connects (also if it connects or reconnects later).
void reportWifi() {
  static bool wasConnected = false;
  bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wasConnected) {
    Serial.printf("WiFi connected, IP %s  (website: setx STATION_URL http://%s)\n",
                  WiFi.localIP().toString().c_str(), WiFi.localIP().toString().c_str());
  } else if (!connected && wasConnected) {
    Serial.println("WiFi lost, reconnecting...");
  }
  wasConnected = connected;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- Scrap scanner starting ---");

#if USE_CAMERA
  if (!psramFound()) Serial.println("WARNING: PSRAM not found - set PSRAM to OPI in Tools menu");
  if (!initCamera()) { Serial.println("Camera init failed"); while (true) delay(1000); }
#endif

  scale.begin(HX711_DT_PIN, HX711_SCK_PIN);
  while (!scale.wait_ready_timeout(1000)) {
    Serial.printf("HX711 not found - check wiring (DT -> GPIO %d, SCK -> GPIO %d, VCC, GND)\n",
                  HX711_DT_PIN, HX711_SCK_PIN);
  }
  scale.set_scale(SCALE_FACTOR);
  Serial.println("Taring... keep the scale empty");
  scale.tare(20);
  Serial.println("Scale ready (zeroed)");

  ESP32PWM::allocateTimer(1);  // camera (if used) already has LEDC timer 0
  // The servo is only attached while it moves (see spin), so nothing moves at power-on.
  Serial.println("Funnel assumed to point at section 1");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("Connecting to WiFi \"%s\"", WIFI_SSID);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_WAIT_MS) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("No WiFi yet - the scale works offline and keeps trying to connect");
  }
  reportWifi();

  web.on("/weight", HTTP_GET, handleWeightRequest);
  web.on("/flap", HTTP_GET, handleFlapRequest);
  web.begin();

#if USE_CAMERA
  if (WiFi.status() == WL_CONNECTED) sendBackground();  // board must be empty at power-on
#endif
  Serial.println("Commands: t = tare, c = calibrate, p = pause printout, 0-4 = move flap,");
  Serial.println("          a / d = nudge flap, r = full circle, q = quarter, w = 4 quarters (calibration)");
}

void loop() {
  handleSerial();
  web.handleClient();
  reportWifi();

  float grams;
  bool stable = readStableWeight(grams);
  if (printWeight) Serial.printf("Weight: %8.1f g  %s\n", grams, stable ? "(settled)" : "(settling)");

#if USE_CAMERA
  if (state == WAIT_FOR_PIECE && stable && grams > PRESENT_G) {
    scanPiece(grams);
    state = WAIT_FOR_REMOVAL;
  } else if (state == WAIT_FOR_REMOVAL && stable && grams < EMPTY_G) {
    Serial.println("Scale empty, ready for next piece");
    state = WAIT_FOR_PIECE;
  }
#endif
}
