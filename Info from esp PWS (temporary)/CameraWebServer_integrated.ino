#include <Arduino.h>
#include "esp_camera.h"
#include "esp_timer.h"
#include <WiFi.h>
#include "esp_wifi.h"
#include "esp_http_server.h"
#include "sauron_poster.h"
#include "elst_map.h"

// ===========================
// Select camera model in board_config.h
// ===========================
#include "board_config.h"

// ===========================
// Enter your WiFi credentials
// ===========================
const char *ssid = "BosbrandDrone";
const char *password = "12345678";

// GPS: GEP-M10-DQ TX -> ESP32 GPIO45, GND -> GND.
// HardwareSerial(1) uses UART1; TX is unused (-1).
static HardwareSerial gpsSerial(1);
static bool gpsDataSeen = false;
static uint32_t lastGpsStatusPrint = 0;
static uint32_t gpsBaudStartedAt = 0;
static uint8_t gpsBaudIndex = 0;
static uint32_t gpsRawBytesPrinted = 0;
static uint8_t gpsRawWindow[32] = {};
static uint8_t gpsRawWindowSize = 0;
static constexpr uint32_t GPS_PRIMARY_BAUD = 115200;
static constexpr uint32_t GPS_BAUDS[] = {115200, 57600, 38400, 9600};
static bool gpsUbxDetected = false;
static uint32_t gpsUbxMessages = 0;
static uint32_t gpsUbxChecksumFailures = 0;

struct GpsState {
  bool hasFix = false;
  uint8_t fixType = 0;
  uint8_t satellites = 0;
  int32_t latitudeE7 = 0;
  int32_t longitudeE7 = 0;
  int32_t altitudeMm = 0;
  int32_t groundSpeedMmS = 0;
  int32_t headingE5 = 0;
  uint16_t hdopHundredths = 0;
  bool hdopValid = false;
};

static GpsState gpsState;

static uint8_t gpsUbxBuffer[256] = {};
static uint16_t gpsUbxLength = 0;
static uint16_t gpsUbxPayloadIndex = 0;
static uint8_t gpsUbxClass = 0;
static uint8_t gpsUbxId = 0;
static uint8_t gpsUbxChecksumA = 0;
static uint8_t gpsUbxChecksumB = 0;
static enum class GpsUbxParserState : uint8_t {
  WaitingForSync,
  GotSyncB5,
  ReadingClass,
  ReadingId,
  ReadingLengthLow,
  ReadingLengthHigh,
  ReadingPayload,
  ReadingChecksumA,
  ReadingChecksumB
} gpsUbxParserState = GpsUbxParserState::WaitingForSync;
static httpd_handle_t cameraHttpServer = nullptr;
static httpd_handle_t cameraStreamServer = nullptr;

// Prioritize newest frames and latency over image detail.
static constexpr framesize_t STREAM_FRAME_SIZE = FRAMESIZE_QQVGA;
static constexpr uint8_t STREAM_JPEG_QUALITY = 22;

static volatile uint32_t streamFramesSent = 0;
static volatile uint32_t streamFramesSkipped = 0;
static volatile uint32_t streamSendErrors = 0;
static volatile uint32_t streamLastFrameBytes = 0;
static volatile uint32_t streamTotalFrameBytes = 0;
static volatile uint32_t streamTotalCaptureUs = 0;
static volatile uint32_t streamTotalSendUs = 0;
static volatile uint32_t streamLastFrameAtMs = 0;

static uint32_t gpsUbxU32(const uint8_t *data) {
  return static_cast<uint32_t>(data[0]) |
         (static_cast<uint32_t>(data[1]) << 8) |
         (static_cast<uint32_t>(data[2]) << 16) |
         (static_cast<uint32_t>(data[3]) << 24);
}

static int32_t gpsUbxI32(const uint8_t *data) {
  return static_cast<int32_t>(gpsUbxU32(data));
}

static uint16_t gpsUbxU16(const uint8_t *data) {
  return static_cast<uint16_t>(data[0]) |
         (static_cast<uint16_t>(data[1]) << 8);
}

static void gpsHandleUbxMessage() {
  ++gpsUbxMessages;
  gpsUbxDetected = true;
  Serial.printf("GPS UBX bericht: class=0x%02X id=0x%02X lengte=%u\n",
                gpsUbxClass, gpsUbxId, gpsUbxLength);

  if (gpsUbxClass != 0x01 || gpsUbxId != 0x07 || gpsUbxLength < 92) {
    return;
  }

  const uint8_t *payload = gpsUbxBuffer;
  gpsState.fixType = payload[20];
  gpsState.hasFix = (payload[21] & 0x01) != 0 &&
                    gpsState.fixType >= 2;
  gpsState.satellites = payload[23];
  gpsState.longitudeE7 = gpsUbxI32(payload + 24);
  gpsState.latitudeE7 = gpsUbxI32(payload + 28);
  gpsState.altitudeMm = gpsUbxI32(payload + 36);
  gpsState.groundSpeedMmS = gpsUbxI32(payload + 60);
  gpsState.headingE5 = gpsUbxI32(payload + 64);
  gpsState.hdopHundredths = gpsUbxU16(payload + 76);
  gpsState.hdopValid = true;
  Serial.printf("GPS fix: type=%u valid=%s sats=%u lat=%.7f lon=%.7f "
                "alt=%.1f m speed=%.2f m/s course=%.2f deg HDOP=%.2f\n",
                gpsState.fixType, gpsState.hasFix ? "yes" : "no",
                gpsState.satellites, gpsState.latitudeE7 / 10000000.0,
                gpsState.longitudeE7 / 10000000.0,
                gpsState.altitudeMm / 1000.0,
                gpsState.groundSpeedMmS / 1000.0,
                gpsState.headingE5 / 100000.0,
                gpsState.hdopHundredths / 100.0);
}

static void gpsUbxReset() {
  gpsUbxParserState = GpsUbxParserState::WaitingForSync;
  gpsUbxLength = 0;
  gpsUbxPayloadIndex = 0;
  gpsUbxChecksumA = 0;
  gpsUbxChecksumB = 0;
}

static void gpsUbxChecksumAdd(uint8_t value) {
  gpsUbxChecksumA = static_cast<uint8_t>(gpsUbxChecksumA + value);
  gpsUbxChecksumB = static_cast<uint8_t>(gpsUbxChecksumB + gpsUbxChecksumA);
}

static void gpsParseUbxByte(uint8_t value) {
  switch (gpsUbxParserState) {
    case GpsUbxParserState::WaitingForSync:
      if (value == 0xB5) {
        gpsUbxParserState = GpsUbxParserState::GotSyncB5;
      }
      break;
    case GpsUbxParserState::GotSyncB5:
      if (value == 0x62) {
        Serial.println("GPS UBX sync gedetecteerd (0xB5 0x62)");
        gpsUbxChecksumA = 0;
        gpsUbxChecksumB = 0;
        gpsUbxParserState = GpsUbxParserState::ReadingClass;
      } else {
        gpsUbxParserState = value == 0xB5
                              ? GpsUbxParserState::GotSyncB5
                              : GpsUbxParserState::WaitingForSync;
      }
      break;
    case GpsUbxParserState::ReadingClass:
      gpsUbxClass = value;
      gpsUbxChecksumAdd(value);
      gpsUbxParserState = GpsUbxParserState::ReadingId;
      break;
    case GpsUbxParserState::ReadingId:
      gpsUbxId = value;
      gpsUbxChecksumAdd(value);
      gpsUbxParserState = GpsUbxParserState::ReadingLengthLow;
      break;
    case GpsUbxParserState::ReadingLengthLow:
      gpsUbxLength = value;
      gpsUbxChecksumAdd(value);
      gpsUbxParserState = GpsUbxParserState::ReadingLengthHigh;
      break;
    case GpsUbxParserState::ReadingLengthHigh:
      gpsUbxLength |= static_cast<uint16_t>(value) << 8;
      gpsUbxChecksumAdd(value);
      if (gpsUbxLength > sizeof(gpsUbxBuffer)) {
        Serial.printf("GPS UBX bericht te groot: %u bytes\n", gpsUbxLength);
        gpsUbxReset();
      } else if (gpsUbxLength == 0) {
        gpsUbxParserState = GpsUbxParserState::ReadingChecksumA;
      } else {
        gpsUbxPayloadIndex = 0;
        gpsUbxParserState = GpsUbxParserState::ReadingPayload;
      }
      break;
    case GpsUbxParserState::ReadingPayload:
      gpsUbxBuffer[gpsUbxPayloadIndex++] = value;
      gpsUbxChecksumAdd(value);
      if (gpsUbxPayloadIndex == gpsUbxLength) {
        gpsUbxParserState = GpsUbxParserState::ReadingChecksumA;
      }
      break;
    case GpsUbxParserState::ReadingChecksumA:
      if (value != gpsUbxChecksumA) {
        ++gpsUbxChecksumFailures;
        Serial.printf("GPS UBX checksum A ongeldig: verwacht=%02X ontvangen=%02X\n",
                      gpsUbxChecksumA, value);
        gpsUbxReset();
      } else {
        gpsUbxParserState = GpsUbxParserState::ReadingChecksumB;
      }
      break;
    case GpsUbxParserState::ReadingChecksumB:
      if (value == gpsUbxChecksumB) {
        gpsHandleUbxMessage();
      } else {
        ++gpsUbxChecksumFailures;
        Serial.printf("GPS UBX checksum B ongeldig: verwacht=%02X ontvangen=%02X\n",
                      gpsUbxChecksumB, value);
      }
      gpsUbxReset();
      break;
  }
}

void setupLedFlash();

static esp_err_t sendCors(httpd_req_t *request) {
  httpd_resp_set_hdr(request, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(request, "Access-Control-Allow-Methods", "GET, OPTIONS");
  httpd_resp_set_hdr(request, "Access-Control-Allow-Headers", "Content-Type");
  return ESP_OK;
}

static esp_err_t optionsHandler(httpd_req_t *request) {
  sendCors(request);
  httpd_resp_send(request, nullptr, 0);
  return ESP_OK;
}

static esp_err_t indexHandler(httpd_req_t *request) {
  static const char page[] =
    "<!doctype html><html><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\">"
    "<title>BosbrandDrone</title><style>"
    "*{box-sizing:border-box}body{margin:0;background:#101419;color:#e8edf2;font:14px Arial,sans-serif}"
    "header{height:46px;padding:12px 16px;background:#182129;border-bottom:1px solid #35404a;font-weight:bold}"
    "header span{float:right;color:#83d98b;font-weight:normal}.grid{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:minmax(260px,48vh) minmax(180px,1fr);gap:10px;padding:10px;height:calc(100vh - 46px)}"
    ".panel{min-height:0;background:#182129;border:1px solid #35404a;border-radius:6px;padding:10px;position:relative;overflow:hidden}.title{color:#9fb1c0;font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px}"
    "#rgb{width:100%;height:calc(100% - 25px);object-fit:contain;background:#080b0e}canvas{width:100%;height:calc(100% - 25px);display:block;background:#0b1014}"
    "#telemetry{display:grid;grid-template-columns:1fr 1fr;gap:8px;align-content:start}.metric{background:#11181e;border-radius:4px;padding:9px}.metric b{display:block;color:#8fa4b5;font-size:11px;margin-bottom:4px}.metric strong{font-size:18px;color:#fff}.wide{grid-column:1/-1}"
    "#message{position:absolute;right:14px;top:12px;color:#f0b56b;font-size:12px}@media(max-width:700px){.grid{grid-template-columns:1fr;grid-template-rows:300px 300px auto auto;height:auto}.panel{min-height:220px}}"
    "</style></head><body><header>BOSBRANDDRONE <span id=state>connecting...</span></header>"
    "<main class=grid><section class=panel><div class=title>RGB camera</div><img id=rgb alt=\"RGB camera stream\"></section>"
    "<section class=panel><div class=title>Thermal camera - hottest point</div><div id=message></div><canvas id=thermal width=320 height=240></canvas></section>"
    "<section class=panel><div class=title>GPS flight map</div><canvas id=map width=640 height=360></canvas></section>"
    "<section class=panel><div class=title>Flight information</div><div id=telemetry>"
    "<div class=metric><b>Altitude MSL</b><strong id=alt>-</strong></div><div class=metric><b>Speed</b><strong id=speed>-</strong></div>"
    "<div class=metric><b>Hotspot</b><strong id=hot>-</strong></div><div class=metric><b>Thermal range</b><strong id=range>-</strong></div>"
    "<div class=\"metric\"><b>Wi-Fi to laptop</b><strong id=wifi>-</strong></div><div class=\"metric\"><b>Wi-Fi RSSI</b><strong id=wifi_rssi>-</strong></div>"
    "<div class=\"metric\"><b>GPS satellites</b><strong id=sats>-</strong></div><div class=\"metric\"><b>GPS signal</b><strong id=gps_quality>-</strong></div>"
    "<div class=\"metric wide\"><b>GPS position</b><strong id=pos>-</strong></div><div class=\"metric wide\"><b>Fix / satellites / HDOP</b><strong id=fix>-</strong></div>"
    "</div></section></main><script>"
    "const rgb=document.getElementById('rgb'),tc=document.getElementById('thermal'),tx=tc.getContext('2d'),mc=document.getElementById('map'),mx=mc.getContext('2d'),trail=[];"
    "let rgbRetryTimer=0,rgbRetryDelay=100;"
    "function connectRgb(){clearTimeout(rgbRetryTimer);document.getElementById('state').textContent='camera verbinden...';rgb.src='http://'+location.hostname+':81/stream?t='+Date.now();}"
    "function retryRgb(){clearTimeout(rgbRetryTimer);document.getElementById('state').textContent='camera opnieuw verbinden...';rgbRetryTimer=setTimeout(connectRgb,rgbRetryDelay);rgbRetryDelay=Math.min(rgbRetryDelay*2,500);}"
    "rgb.onload=()=>{rgbRetryDelay=100;document.getElementById('state').textContent='online'};"
    "rgb.onerror=retryRgb;"
    "window.addEventListener('online',connectRgb);"
    "connectRgb();"
    "function val(v,u){return v==null||!isFinite(v)?'-':Number(v).toFixed(1)+' '+u}"
    "function wifiLabel(rssi){if(rssi==null||!isFinite(rssi))return 'no client';if(rssi>=-55)return 'excellent';if(rssi>=-67)return 'good';if(rssi>=-75)return 'fair';if(rssi>=-90)return 'weak';return 'very weak';}"
    "function wifiPercent(rssi){if(rssi==null||!isFinite(rssi))return 0;let q=Math.max(0,Math.min(100,Math.round((rssi+100)*1.6)));return q;}"
    "function color(t,a,b){let x=(t-a)/(b-a||1);x=Math.max(0,Math.min(1,x));let r=Math.round(255*Math.min(1,2*x)),g=Math.round(255*Math.min(1,2-2*x)),b2=Math.round(255*Math.max(0,1-2*x));return 'rgb('+r+','+g+','+b2+')'}"
    "function thermal(d){tx.clearRect(0,0,tc.width,tc.height);if(!d.frame){document.getElementById('message').textContent='thermal sensor unavailable';return}let a=d.thermal.min_c,b=d.thermal.max_c,w=tc.width/32,h=tc.height/24;"
    "d.frame.forEach((t,i)=>{if(t!=null){tx.fillStyle=color(t,a,b);tx.fillRect(i%32*w,Math.floor(i/32)*h,Math.ceil(w),Math.ceil(h))}});let p=d.thermal.hotspot;tx.strokeStyle='#fff';tx.lineWidth=2;tx.strokeRect(p.x*w,p.y*h,w,h);document.getElementById('hot').textContent=val(b,'C');document.getElementById('range').textContent=val(a,'C')+' - '+val(b,'C');document.getElementById('message').textContent='hotspot x'+p.x+' y'+p.y}"
    "const mapBounds={minLat:51.90544,maxLat:51.91454,minLon:5.81623,maxLon:5.84168};"
    "const elstMap=" ELST_MAP_DATA ";"
    "function mapPoint(lat,lon){return {x:(lon-mapBounds.minLon)/(mapBounds.maxLon-mapBounds.minLon)*mc.width,y:mc.height-(lat-mapBounds.minLat)/(mapBounds.maxLat-mapBounds.minLat)*mc.height};}"
    "function mapLine(points,color,width){mx.beginPath();points.forEach((q,i)=>{let z=mapPoint(q[0],q[1]);if(i)mx.lineTo(z.x,z.y);else mx.moveTo(z.x,z.y)});mx.strokeStyle=color;mx.lineWidth=width;mx.stroke();}"
    "function mapLabel(text,lat,lon){let z=mapPoint(lat,lon);mx.fillStyle='#314350';mx.font='bold 11px Arial';mx.fillText(text,z.x+4,z.y-4);}"
    "function map(p){"
    "mx.clearRect(0,0,mc.width,mc.height);mx.fillStyle='#dce8d2';mx.fillRect(0,0,mc.width,mc.height);"
    "const roadStyle={M:['#d18b35',3],T:['#e4ad55',2.5],R:['#ffffff',2],L:['#ffffff',1.5],U:['#ffffff',1.5],S:['#f5f5f5',1],C:['#82a96b',1.2]};"
    "elstMap.forEach(w=>{let s=roadStyle[w.t]||roadStyle.R;mapLine(w.p.map(q=>[mapBounds.minLat+q[0]/100000,mapBounds.minLon+q[1]/100000]),s[0],s[1]);});"
    "elstMap.forEach(w=>{if(w.n&&(w.t==='M'||w.t==='T')){let q=w.p[Math.floor(w.p.length/2)];mapLabel(w.n,mapBounds.minLat+q[0]/100000,mapBounds.minLon+q[1]/100000);}});"
    "mapLabel('Elst',51.9108,5.8265);mx.fillStyle='#536b77';mx.font='11px Arial';mx.fillText('offline OpenStreetMap · Elst',10,17);"
    "if(!p||p.lat==null||p.lon==null){mx.fillStyle='#314350';mx.font='14px Arial';mx.fillText('Waiting for GPS fix...',15,38);return}"
    "trail.push([Number(p.lat),Number(p.lon)]);if(trail.length>200)trail.shift();"
    "mx.setLineDash([5,4]);mapLine(trail,'#1685c7',2);mx.setLineDash([]);"
    "let z=mapPoint(Number(p.lat),Number(p.lon));mx.fillStyle='#e3342f';mx.beginPath();mx.arc(z.x,z.y,8,0,7);mx.fill();mx.strokeStyle='#fff';mx.lineWidth=2;mx.stroke();"
    "mx.fillStyle='#1f2c33';mx.font='bold 11px Arial';mx.fillText(Number(p.lat).toFixed(6)+', '+Number(p.lon).toFixed(6),z.x+10,z.y+4);}"
    "async function update(){"
    "try{let r=await fetch('/api/data',{cache:'no-store'});if(r.ok)thermal(await r.json());}"
    "catch(e){document.getElementById('message').textContent='thermal data unavailable';}"
    "try{let g=await fetch('/api/gps',{cache:'no-store'});if(!g.ok)throw Error('GPS HTTP '+g.status);let p=await g.json();"
    "map(p);document.getElementById('alt').textContent=val(p.alt_msl,'m');"
    "document.getElementById('speed').textContent=val(p.speed_mps,'m/s');"
    "document.getElementById('pos').textContent=p.lat==null?'-':Number(p.lat).toFixed(6)+', '+Number(p.lon).toFixed(6);"
    "document.getElementById('fix').textContent=(p.fix==null?'-':p.fix)+' / '+(p.sats==null?'-':p.sats)+' / '+val(p.hdop,'');"
    "document.getElementById('sats').textContent=p.sats==null?'-':String(p.sats);"
    "document.getElementById('gps_quality').textContent=(p.hdop==null||!isFinite(p.hdop))?'-':(p.hdop<2?'excellent':p.hdop<5?'good':p.hdop<8?'fair':'weak');}"
    "catch(e){map(null);document.getElementById('alt').textContent='-';document.getElementById('speed').textContent='-';"
    "document.getElementById('pos').textContent='-';document.getElementById('fix').textContent='-';"
    "document.getElementById('sats').textContent='-';document.getElementById('gps_quality').textContent='-';}"
    "try{let s=await fetch('/api/status',{cache:'no-store'});if(!s.ok)throw Error('status HTTP '+s.status);let st=await s.json();"
    "let rssi=st&&st.wifi&&st.wifi.rssi_dbm!=null?Number(st.wifi.rssi_dbm):-Infinity;"
    "let wifiQuality=wifiLabel(rssi),wifiSignalPercent=wifiPercent(rssi);"
    "document.getElementById('wifi').textContent=wifiQuality+' ('+wifiSignalPercent+'%)';"
    "document.getElementById('wifi_rssi').textContent=rssi===-Infinity?'-':rssi+' dBm';"
    "document.getElementById('state').textContent=(rgb.complete&&rgb.naturalWidth)?'online · Wi-Fi '+wifiSignalPercent+'%':'offline';}"
    "catch(e){document.getElementById('wifi').textContent='no client';document.getElementById('wifi_rssi').textContent='-';"
    "document.getElementById('state').textContent=(rgb.complete&&rgb.naturalWidth)?'online':'offline';}"
    "}setInterval(update,250);update();</script></body></html>";
  sendCors(request);
  httpd_resp_set_type(request, "text/html; charset=utf-8");
  httpd_resp_send(request, page, HTTPD_RESP_USE_STRLEN);
  return ESP_OK;
}

static esp_err_t captureHandler(httpd_req_t *request) {
  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR,
                        "Camera capture failed");
    return ESP_FAIL;
  }

  sendCors(request);
  httpd_resp_set_type(request, "image/jpeg");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  esp_err_t result = httpd_resp_send(request,
                                     reinterpret_cast<const char *>(frame->buf),
                                     frame->len);
  esp_camera_fb_return(frame);
  return result;
}

static void addNoCacheHeaders(httpd_req_t *request) {
  httpd_resp_set_hdr(request, "Cache-Control", "no-store, no-cache, must-revalidate");
  httpd_resp_set_hdr(request, "Pragma", "no-cache");
  httpd_resp_set_hdr(request, "Connection", "keep-alive");
  httpd_resp_set_hdr(request, "X-Accel-Buffering", "no");
}

static esp_err_t streamHandler(httpd_req_t *request) {
  static const char *contentType =
    "multipart/x-mixed-replace;boundary=frame";
  static const char *boundary = "\r\n--frame\r\n";
  static const char *part = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

  sendCors(request);
  httpd_resp_set_type(request, contentType);
  addNoCacheHeaders(request);
  httpd_resp_set_hdr(request, "Access-Control-Expose-Headers", "Cache-Control");

  while (true) {
    const int64_t captureStartedUs = esp_timer_get_time();
    camera_fb_t *frame = esp_camera_fb_get();
    const uint32_t captureUs =
      static_cast<uint32_t>(esp_timer_get_time() - captureStartedUs);
    if (frame == nullptr) {
      ++streamSendErrors;
      return ESP_FAIL;
    }

    const size_t frameLength = frame->len;
    char header[128];
    int headerLength = snprintf(header, sizeof(header), "%s%s", boundary, "");
    if (headerLength >= 0) {
      headerLength += snprintf(header + headerLength,
                               sizeof(header) - static_cast<size_t>(headerLength),
                               part,
                                static_cast<unsigned int>(frameLength));
    }
    const int64_t sendStartedUs = esp_timer_get_time();
    esp_err_t result = headerLength < 0 ||
                       static_cast<size_t>(headerLength) >= sizeof(header)
                         ? ESP_ERR_INVALID_SIZE
                         : httpd_resp_send_chunk(request, header, headerLength);
    if (result == ESP_OK) {
      result = httpd_resp_send_chunk(
        request, reinterpret_cast<const char *>(frame->buf), frameLength);
    }
    esp_camera_fb_return(frame);
    const uint32_t sendUs =
      static_cast<uint32_t>(esp_timer_get_time() - sendStartedUs);
    if (result != ESP_OK) {
      ++streamSendErrors;
      return result;
    }

    ++streamFramesSent;
    streamLastFrameBytes = static_cast<uint32_t>(frameLength);
    streamTotalFrameBytes += static_cast<uint32_t>(frameLength);
    streamTotalCaptureUs += captureUs;
    streamTotalSendUs += sendUs;
    streamLastFrameAtMs = millis();
  }
}

static esp_err_t dataHandler(httpd_req_t *request) {
  const char *json = sauronLaatsteJson();
  sendCors(request);
  httpd_resp_set_type(request, "application/json");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store, no-cache, must-revalidate");
  if (json == nullptr) {
    httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR,
                        "Thermal frame is not available");
    return ESP_FAIL;
  }
  httpd_resp_send(request, json, HTTPD_RESP_USE_STRLEN);
  return ESP_OK;
}

static esp_err_t gpsHandler(httpd_req_t *request) {
  const char *json = sauronLaatsteGpsJson(gpsDataSeen);
  if (json == nullptr) {
    httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR,
                        "GPS response is too large");
    return ESP_FAIL;
  }
  sendCors(request);
  httpd_resp_set_type(request, "application/json");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  httpd_resp_send(request, json, HTTPD_RESP_USE_STRLEN);
  return ESP_OK;
}

static esp_err_t statusHandler(httpd_req_t *request) {
  char json[512];
  const uint32_t frames = streamFramesSent;
  const uint32_t averageBytes = frames == 0
                                  ? 0
                                  : streamTotalFrameBytes / frames;
  const uint32_t averageCaptureUs = frames == 0
                                      ? 0
                                      : streamTotalCaptureUs / frames;
  const uint32_t averageSendUs = frames == 0
                                   ? 0
                                   : streamTotalSendUs / frames;
  int8_t rssiDbm = -127;
  uint8_t stationCount = WiFi.softAPgetStationNum();
  if (stationCount > 0) {
    wifi_sta_list_t stations = {};
    if (esp_wifi_ap_get_sta_list(&stations) == ESP_OK) {
      int32_t sum = 0;
      uint8_t activeStations = 0;
      for (uint8_t i = 0; i < stations.num; ++i) {
        const int8_t stationRssi = stations.sta[i].rssi;
        if (stationRssi != 0) {
          sum += stationRssi;
          ++activeStations;
        }
      }
      if (activeStations > 0) {
        rssiDbm = static_cast<int8_t>(sum / static_cast<int32_t>(activeStations));
      }
    }
  }

  int signalPercent = 0;
  if (rssiDbm > -127) {
    signalPercent = static_cast<int>(constrain((rssiDbm + 100.0f) * 1.6f, 0.0f, 100.0f));
  }
  const char *wifiQuality = "no client";
  if (rssiDbm > -127) {
    if (rssiDbm >= -55) {
      wifiQuality = "excellent";
    } else if (rssiDbm >= -67) {
      wifiQuality = "good";
    } else if (rssiDbm >= -75) {
      wifiQuality = "fair";
    } else if (rssiDbm >= -90) {
      wifiQuality = "weak";
    } else {
      wifiQuality = "very weak";
    }
  }

  int length = snprintf(
    json, sizeof(json),
    "{\"wifi\":{\"mode\":\"AP\",\"ssid\":\"%s\",\"ip\":\"%s\",\"clients\":%u,\"rssi_dbm\":%d,\"signal_percent\":%d,\"quality\":\"%s\"},"
    "\"camera\":true,\"thermal\":{\"available\":%s,\"status\":\"%s\","
    "\"frame_errors\":%lu},\"gps\":{\"data_seen\":%s,"
    "\"location_valid\":%s,\"baud\":%lu,\"rx_gpio\":45,"
    "\"bytes_seen\":%lu,\"ubx_detected\":%s,\"ubx_messages\":%lu,"
    "\"checksum_failures\":%lu,\"protocol\":\"%s\","
    "\"fix_type\":%u,\"satellites\":%u},"
    "\"stream\":{\"frames_sent\":%lu,\"frames_skipped\":%lu,"
    "\"send_errors\":%lu,\"last_frame_bytes\":%lu,"
    "\"average_frame_bytes\":%lu,\"average_capture_us\":%lu,"
    "\"average_send_us\":%lu,\"last_frame_at_ms\":%lu}}",
    ssid, WiFi.softAPIP().toString().c_str(),
    static_cast<unsigned int>(stationCount),
    rssiDbm,
    signalPercent,
    wifiQuality,
    sauronHeeftFrame() ? "true" : "false",
    sauronStatus(), static_cast<unsigned long>(sauronFrameErrorCount()),
    gpsDataSeen ? "true" : "false",
    gpsState.hasFix ? "true" : "false",
    static_cast<unsigned long>(GPS_BAUDS[gpsBaudIndex]),
    static_cast<unsigned long>(gpsRawBytesPrinted),
    gpsUbxDetected ? "true" : "false",
    static_cast<unsigned long>(gpsUbxMessages),
    static_cast<unsigned long>(gpsUbxChecksumFailures),
    gpsUbxDetected ? "UBX" : "unknown",
    gpsState.fixType,
    gpsState.satellites,
    static_cast<unsigned long>(frames),
    static_cast<unsigned long>(streamFramesSkipped),
    static_cast<unsigned long>(streamSendErrors),
    static_cast<unsigned long>(streamLastFrameBytes),
    static_cast<unsigned long>(averageBytes),
    static_cast<unsigned long>(averageCaptureUs),
    static_cast<unsigned long>(averageSendUs),
    static_cast<unsigned long>(streamLastFrameAtMs));
  if (length < 0 || static_cast<size_t>(length) >= sizeof(json)) {
    httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR,
                        "Status response is too large");
    return ESP_FAIL;
  }
  sendCors(request);
  httpd_resp_set_type(request, "application/json");
  httpd_resp_send(request, json, length);
  return ESP_OK;
}

static void registerRoute(httpd_handle_t server, const char *uri,
                          httpd_method_t method, esp_err_t (*handler)(httpd_req_t *)) {
  httpd_uri_t route = {};
  route.uri = uri;
  route.method = method;
  route.handler = handler;
  httpd_register_uri_handler(server, &route);
}

static void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.max_uri_handlers = 16;
  config.stack_size = 8192;
  config.send_wait_timeout = 1;
  config.recv_wait_timeout = 1;
  config.lru_purge_enable = true;

  if (httpd_start(&cameraHttpServer, &config) != ESP_OK) {
    Serial.println("Failed to start HTTP server");
    return;
  }
  registerRoute(cameraHttpServer, "/", HTTP_GET, indexHandler);
  registerRoute(cameraHttpServer, "/capture", HTTP_GET, captureHandler);
  registerRoute(cameraHttpServer, "/api/data", HTTP_GET, dataHandler);
  registerRoute(cameraHttpServer, "/api/gps", HTTP_GET, gpsHandler);
  registerRoute(cameraHttpServer, "/api/status", HTTP_GET, statusHandler);
  registerRoute(cameraHttpServer, "/api/data", HTTP_OPTIONS, optionsHandler);
  registerRoute(cameraHttpServer, "/api/gps", HTTP_OPTIONS, optionsHandler);
  registerRoute(cameraHttpServer, "/api/status", HTTP_OPTIONS, optionsHandler);

  config.server_port = 81;
  config.ctrl_port = 32769;
  if (httpd_start(&cameraStreamServer, &config) == ESP_OK) {
    registerRoute(cameraStreamServer, "/stream", HTTP_GET, streamHandler);
  } else {
    Serial.println("Failed to start camera stream server");
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size = STREAM_FRAME_SIZE;
  config.pixel_format = PIXFORMAT_JPEG;  // for streaming
  //config.pixel_format = PIXFORMAT_RGB565; // for face detection/recognition
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = STREAM_JPEG_QUALITY;
  // Two buffers allow the camera driver to keep capturing while the
  // previous JPEG is being sent; CAMERA_GRAB_LATEST drops older frames.
  config.fb_count = 2;

  // if PSRAM IC present, init with UXGA resolution and higher JPEG quality
  //                      for larger pre-allocated frame buffer.
  if (config.pixel_format == PIXFORMAT_JPEG) {
    if (psramFound()) {
      config.jpeg_quality = STREAM_JPEG_QUALITY;
      config.fb_count = 2;
      config.grab_mode = CAMERA_GRAB_LATEST;
    } else {
      // Keep the no-PSRAM fallback small enough for low latency and DRAM.
      config.frame_size = STREAM_FRAME_SIZE;
      config.fb_location = CAMERA_FB_IN_DRAM;
    }
  } else {
    // Best option for face detection/recognition
    config.frame_size = FRAMESIZE_240X240;
#if CONFIG_IDF_TARGET_ESP32S3
    config.fb_count = 2;
#endif
  }

#if defined(CAMERA_MODEL_ESP_EYE)
  pinMode(13, INPUT_PULLUP);
  pinMode(14, INPUT_PULLUP);
#endif

  // camera init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  sensor_t *s = esp_camera_sensor_get();
  // initial sensors are flipped vertically and colors are a bit saturated
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);        // flip it back
    s->set_brightness(s, 1);   // up the brightness just a bit
    s->set_saturation(s, -2);  // lower the saturation
  }
  // drop down frame size for higher initial frame rate
  if (config.pixel_format == PIXFORMAT_JPEG) {
    s->set_framesize(s, STREAM_FRAME_SIZE);
  }

#if defined(CAMERA_MODEL_M5STACK_WIDE) || defined(CAMERA_MODEL_M5STACK_ESP32CAM)
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);
#endif

#if defined(CAMERA_MODEL_ESP32S3_EYE)
  s->set_vflip(s, 1);
#endif

// Setup LED FLash if LED pin is defined in camera_pins.h
#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif
  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);
  if (esp_wifi_set_ps(WIFI_PS_NONE) != ESP_OK) {
    Serial.println("Warning: WiFi power-save could not be disabled");
  }

  Serial.println("Starting WiFi access point...");

  if (!WiFi.softAP(ssid, password, 6, false, 1)) {
    Serial.println("Failed to start WiFi AP!");
    return;
  }

  Serial.println("WiFi AP started!");
  Serial.print("SSID: ");
  Serial.println(ssid);
  Serial.print("Password: ");
  Serial.println(password);

  Serial.print("Camera Ready! Use 'http://");
  Serial.print(WiFi.softAPIP());
  Serial.println("' to connect");

  startCameraServer();

  // Start GPS UART after camera and Wi-Fi initialization.
  gpsSerial.begin(GPS_PRIMARY_BAUD, SERIAL_8N1, 45, -1);
  gpsBaudStartedAt = millis();
  Serial.println("GPS UART gestart (115200 baud, RX GPIO45)");

  // Initialize thermal sensor and laptop sender. RGB streaming remains intact.
  sauronBegin();
}

void loop() {
  // Thermal capture has priority over GPS parsing and optional dashboard POST.
  // This keeps the local HTTP thermal endpoint current even without a GPS fix.
  sauronLoop();

  // Parse all bytes currently available from the GPS receiver.
  while (gpsSerial.available() > 0) {
    const int c = gpsSerial.read();
    if (c >= 0) {
      gpsDataSeen = true;
      gpsParseUbxByte(static_cast<uint8_t>(c));
      gpsRawWindow[gpsRawBytesPrinted % sizeof(gpsRawWindow)] =
        static_cast<uint8_t>(c);
      if (gpsRawWindowSize < sizeof(gpsRawWindow)) {
        ++gpsRawWindowSize;
      }
      ++gpsRawBytesPrinted;
    }

  }

  if (!gpsUbxDetected &&
      gpsBaudIndex + 1 < sizeof(GPS_BAUDS) / sizeof(GPS_BAUDS[0]) &&
      millis() - gpsBaudStartedAt >= 8000UL) {
    ++gpsBaudIndex;
    gpsSerial.updateBaudRate(GPS_BAUDS[gpsBaudIndex]);
    gpsBaudStartedAt = millis();
    Serial.printf("Geen geldig UBX-bericht; probeer %lu baud.\n",
                  static_cast<unsigned long>(GPS_BAUDS[gpsBaudIndex]));
  }

  if (millis() - lastGpsStatusPrint >= 5000UL) {
    lastGpsStatusPrint = millis();
    Serial.printf("GPS status: baud=%lu, bytes=%lu, UBX=%s, berichten=%lu, "
                  "formaat=%s, fix=%s, fix_type=%u, sats=%u\n",
                  static_cast<unsigned long>(GPS_BAUDS[gpsBaudIndex]),
                  static_cast<unsigned long>(gpsRawBytesPrinted),
                  gpsUbxDetected ? "yes" : "no",
                  static_cast<unsigned long>(gpsUbxMessages),
                  gpsUbxDetected ? "UBX binary" : "unknown/binary",
                  gpsState.hasFix ? "yes" : "no",
                  gpsState.fixType, gpsState.satellites);
    Serial.print("GPS raw latest: ");
    const uint32_t firstRawByte =
      gpsRawBytesPrinted >= gpsRawWindowSize
        ? gpsRawBytesPrinted - gpsRawWindowSize
        : 0;
    for (uint8_t i = 0; i < gpsRawWindowSize; ++i) {
      const uint8_t index =
        static_cast<uint8_t>((firstRawByte + i) % sizeof(gpsRawWindow));
      Serial.printf("%02X ", static_cast<unsigned int>(gpsRawWindow[index]));
    }
    Serial.println();
  }

  // Send the latest UBX NAV-PVT values to sauron_poster.h.
  if (gpsState.hasFix) {
    sauronSetGps(
      gpsState.latitudeE7 / 10000000.0f,
      gpsState.longitudeE7 / 10000000.0f,
      gpsState.altitudeMm / 1000.0f,
      gpsState.headingE5 / 100000.0f,
      gpsState.groundSpeedMmS / 1000.0f,
      gpsState.fixType,
      gpsState.satellites,
      gpsState.hdopValid ? gpsState.hdopHundredths / 100.0f : NAN);
  } else {
    // Keep status and satellite count visible until a valid position is available.
    sauronSetGps(NAN, NAN, NAN, NAN, NAN, gpsState.fixType,
                 gpsState.satellites,
                 gpsState.hdopValid ? gpsState.hdopHundredths / 100.0f : NAN);
  }

  // Avoid a busy loop while keeping GPS parsing responsive.
  delay(1);
}
