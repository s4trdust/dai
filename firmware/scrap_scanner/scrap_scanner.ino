// Scrap scanner firmware - Freenove ESP32-S3 WROOM CAM + HX711 load cell + servo flap
//
// Arduino IDE settings:  Board "ESP32S3 Dev Module", PSRAM "OPI PSRAM",
//                        Flash size to match your board (usually 8MB or 16MB)
// Libraries (Library Manager):  "HX711" by Bogdan Necula, "ArduinoJson" by Benoit Blanchon,
//                               "ESP32Servo" by Kevin Harrington
//
// Flow: wait for a stable weight -> take photo -> POST to the website -> move flap to
//       the returned section (or manual area) -> wait until the piece is removed -> repeat.
//
// Serial commands (115200 baud):  t = tare scale,  b = resend empty-board photo,
//                                 c = print raw reading for calibration

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include "esp_camera.h"
#include "HX711.h"

// ---------------- Settings to edit ----------------
const char* WIFI_SSID   = "YOUR_WIFI";
const char* WIFI_PASS   = "YOUR_PASSWORD";
const char* SERVER_URL  = "http://192.168.1.50:5000";  // IP of the PC running the website

const int   HX711_DT_PIN  = 14;
const int   HX711_SCK_PIN = 21;
float       SCALE_FACTOR  = 420.0f;   // raw units per gram - see calibration in README

const int   SERVO_PIN = 47;
// Flap angle per destination: index 0 = manual area, 1-4 = storage sections 1-4
// (what each section holds is set on the website side in station/config.py)
const int   SECTION_ANGLES[5] = {175, 20, 60, 100, 140};
const int   MANUAL_AREA = 0;          // also used if the website can't be reached

const float PRESENT_G      = 5.0f;    // above this, a piece is on the scale
const float EMPTY_G        = 2.0f;    // below this, the scale is empty again
const float STABLE_RANGE_G = 0.5f;    // max wobble between readings to count as settled
const int   STABLE_SAMPLES = 8;

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

HX711 scale;
Servo flap;
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

void moveFlap(int section) {
  if (section < 0 || section > 4) section = MANUAL_AREA;
  flap.write(SECTION_ANGLES[section]);
  if (section == MANUAL_AREA) Serial.println("Flap -> manual area");
  else Serial.printf("Flap -> section %d\n", section);
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
  Serial.printf("Item %ld: %s (quantity now %d)\n", doc["item_id"].as<long>(),
                doc["name"] | "?", doc["quantity"] | 1);
  moveFlap(doc["section"] | MANUAL_AREA);
}

void handleSerial() {
  if (!Serial.available()) return;
  char cmd = Serial.read();
  if (cmd == 't') { scale.tare(20); Serial.println("Tared"); }
  if (cmd == 'b') sendBackground();
  if (cmd == 'c') {
    // Put a known weight on, then SCALE_FACTOR = printed value / known grams.
    Serial.printf("Raw (tared) reading: %.1f\n", scale.get_value(20));
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  if (!psramFound()) Serial.println("WARNING: PSRAM not found - set PSRAM to OPI in Tools menu");
  if (!initCamera()) { Serial.println("Camera init failed"); while (true) delay(1000); }

  scale.begin(HX711_DT_PIN, HX711_SCK_PIN);
  scale.set_scale(SCALE_FACTOR);
  scale.tare(20);

  ESP32PWM::allocateTimer(1);  // camera already uses LEDC timer 0
  flap.attach(SERVO_PIN);
  moveFlap(MANUAL_AREA);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\nConnected, IP %s\n", WiFi.localIP().toString().c_str());

  sendBackground();  // board must be empty at power-on
}

void loop() {
  handleSerial();
  float grams;
  bool stable = readStableWeight(grams);

  if (state == WAIT_FOR_PIECE && stable && grams > PRESENT_G) {
    scanPiece(grams);
    state = WAIT_FOR_REMOVAL;
  } else if (state == WAIT_FOR_REMOVAL && stable && grams < EMPTY_G) {
    Serial.println("Scale empty, ready for next piece");
    state = WAIT_FOR_PIECE;
  }
}
