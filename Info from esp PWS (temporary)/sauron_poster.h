
#pragma once

// sauron_poster.h
// MLX90640 thermische camera + GPS-data naar het dashboard.
// Geschikt als toevoeging aan de ESP32-S3 CameraWebServer.
//
// De MLX90640 Melexis API en ESP32 I2C-driver staan naast dit bestand.
//
// Aansluitingen MLX90640:
//   VIN -> 3V3
//   GND -> GND
//   SDA -> GPIO1 (B1)
//   SCL -> GPIO40 (B40)
//
// GPS wordt vanuit CameraWebServer_integrated.ino aangeleverd via:
//   sauronSetGps(...)
//
// Gebruik:
//   setup(): sauronBegin();
//   loop():  sauronLoop();

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <HTTPClient.h>
#include <Wire.h>
#include "MLX90640_API.h"
#include "MLX90640_I2C_Driver.h"
#include <stdarg.h>
#include <math.h>
#include <string.h>

// ============================================================
// CONFIGURATIE
// ============================================================

#ifndef SAURON_SDA
#define SAURON_SDA 1   // GPIO1 (B1) - MLX90640 SDA
#endif

#ifndef SAURON_SCL
#define SAURON_SCL 40  // GPIO40 (B40) - MLX90640 SCL  
#endif

#define SAURON_I2C_ADDR 0x33

// Lees de sensor op de ingestelde refresh rate; verzend hoogstens eenmaal
// per seconde naar het optionele externe dashboard.
#define SAURON_READ_INTERVAL_MS 125UL
#define SAURON_POST_INTERVAL_MS 1000UL

// UDP-poort voor ontdekking van de laptop.
#define SAURON_UDP_POORT 8001

// 768 pixels, plus GPS-gegevens en JSON-overhead.
#define SAURON_BUF (768 * 12 + 2048)

// Oriëntatie aanpassen als het thermische beeld verkeerd staat.
#define SAURON_TRANSPOSE 0
#define SAURON_MIRROR_X 0

// ============================================================
// STATUS EN DATA
// ============================================================

static paramsMLX90640 sauronMlx;
static WiFiUDP sauronUdp;

static float sauronRuw[768];
static float sauronFrame[768];
static uint16_t sauronFrameData[834];

static char sauronBody[SAURON_BUF];

static bool sauronLive = false;
static bool sauronFrameReady = false;
static bool sauronInitAttempted = false;
static uint32_t sauronLastInitAttempt = 0;
static uint32_t sauronFrameErrors = 0;
static const char *sauronError = "not_initialized";
static uint32_t sauronLaatsteUitlezing = 0;
static uint32_t sauronLaatsteVerzending = 0;
static String sauronDoel;

// GPS-gegevens
static float sauronLat = NAN;
static float sauronLon = NAN;
static float sauronAltMsl = NAN;
static float sauronHeading = NAN;
static float sauronSpeedMps = NAN;
static float sauronHdop = NAN;

static int sauronFix = -1;
static int sauronSats = -1;

static float sauronLaunchMsl = NAN;
static float sauronMinTemp = NAN;
static float sauronMaxTemp = NAN;
static int sauronHotspotX = -1;
static int sauronHotspotY = -1;

// ============================================================
// VEILIG JSON OPBOUWEN
// ============================================================

static bool sauronAppend(size_t &used, const char *format, ...) {
  if (used >= sizeof(sauronBody)) {
    return false;
  }

  va_list args;
  va_start(args, format);

  const size_t remaining = sizeof(sauronBody) - used;

  int written = vsnprintf(
    sauronBody + used,
    remaining,
    format,
    args
  );

  va_end(args);

  if (written < 0 || (size_t)written >= remaining) {
    return false;
  }

  used += (size_t)written;
  return true;
}

// ============================================================
// LAPTOP ONTDEKKEN VIA UDP
// ============================================================

static bool sauronVindDoel() {
  uint8_t buf[256];

  IPAddress lokaal =
    (WiFi.getMode() & WIFI_MODE_AP)
      ? WiFi.softAPIP()
      : WiFi.localIP();

  IPAddress bcast(
    lokaal[0],
    lokaal[1],
    lokaal[2],
    255
  );

  for (uint8_t poging = 0; poging < 3; poging++) {

    // Broadcast op het huidige lokale subnet.
    sauronUdp.beginPacket(bcast, SAURON_UDP_POORT);
    sauronUdp.write(
      (const uint8_t *)"SAURON?",
      7
    );
    sauronUdp.endPacket();

    // Ook een algemene broadcast proberen bij verbinding
    // met een bestaand WiFi-netwerk.
    if (WiFi.status() == WL_CONNECTED) {
      sauronUdp.beginPacket(
        IPAddress(255, 255, 255, 255),
        SAURON_UDP_POORT
      );

      sauronUdp.write(
        (const uint8_t *)"SAURON?",
        7
      );

      sauronUdp.endPacket();
    }

    uint32_t start = millis();

    while (millis() - start < 300) {
      int packetSize = sauronUdp.parsePacket();

      if (packetSize > 0) {
        int len = sauronUdp.read(
          buf,
          sizeof(buf) - 1
        );

        if (len > 0) {
          buf[len] = '\0';

          String antwoord = String((char *)buf);
          antwoord.trim();

          if (antwoord.startsWith("http://") ||
              antwoord.startsWith("https://")) {

            sauronDoel = antwoord;

            Serial.printf(
              "[sauron] Dashboard gevonden: %s\n",
              sauronDoel.c_str()
            );

            return true;
          }
        }
      }

      delay(5);
    }
  }

  Serial.println(
    "[sauron] Dashboard niet gevonden via UDP."
  );

  return false;
}

// ============================================================
// THERMISCH FRAME OMBOUWEN
// ============================================================

static void sauronOmbouwen() {
  for (int rij = 0; rij < 24; rij++) {
    for (int kolom = 0; kolom < 32; kolom++) {

      int bron;

#if SAURON_TRANSPOSE
      bron = kolom * 24 + rij;
#else
      bron = rij * 32 + kolom;
#endif

#if SAURON_MIRROR_X
      int doel = rij * 32 + (31 - kolom);
#else
      int doel = rij * 32 + kolom;
#endif

      if (bron >= 0 && bron < 768 &&
          doel >= 0 && doel < 768) {
        sauronFrame[doel] = sauronRuw[bron];
      }
    }
  }
}

// ============================================================
// JSON MET THERMISCHE DATA EN GPS
// ============================================================

static bool sauronBouwBody() {
  size_t n = 0;
  sauronMinTemp = INFINITY;
  sauronMaxTemp = -INFINITY;
  sauronHotspotX = -1;
  sauronHotspotY = -1;
  uint16_t geldigePixels = 0;

  for (int i = 0; i < 768; i++) {
    if (!isnan(sauronFrame[i]) && !isinf(sauronFrame[i])) {
      geldigePixels++;
      if (sauronFrame[i] < sauronMinTemp) {
        sauronMinTemp = sauronFrame[i];
      }
      if (sauronFrame[i] > sauronMaxTemp) {
        sauronMaxTemp = sauronFrame[i];
        sauronHotspotX = i % 32;
        sauronHotspotY = i / 32;
      }
    }
  }

  if (geldigePixels == 0) {
    sauronError = "mlx90640_invalid_frame";
    return false;
  }

  if (!sauronAppend(n, "{\"thermal_available\":true,\"frame\":[")) {
    return false;
  }

  for (int i = 0; i < 768; i++) {
    if (i > 0) {
      if (!sauronAppend(n, ",")) {
        return false;
      }
    }

    // JSON ondersteunt geen NaN of Infinity.
    if (isnan(sauronFrame[i]) ||
        isinf(sauronFrame[i])) {

      if (!sauronAppend(n, "null")) {
        return false;
      }

    } else {
      if (!sauronAppend(
            n,
            "%.1f",
            (double)sauronFrame[i])) {
        return false;
      }
    }
  }

  if (!sauronAppend(n, "]")) {
    return false;
  }

  if (!sauronAppend(n, ",\"thermal\":{\"min_c\":%.1f,\"max_c\":%.1f,"
                       "\"hotspot\":{\"x\":%d,\"y\":%d}}",
                    (double)sauronMinTemp, (double)sauronMaxTemp,
                    sauronHotspotX, sauronHotspotY)) {
    return false;
  }

  // GPS-object alleen opnemen bij geldige coördinaten.
  if (!isnan(sauronLat) &&
      !isnan(sauronLon) &&
      !isinf(sauronLat) &&
      !isinf(sauronLon)) {

    if (!sauronAppend(
          n,
          ",\"drone\":{\"lat\":%.6f,\"lon\":%.6f",
          (double)sauronLat,
          (double)sauronLon)) {
      return false;
    }

    if (!isnan(sauronAltMsl) &&
        !isinf(sauronAltMsl)) {

      if (!sauronAppend(
            n,
            ",\"alt_msl\":%.1f",
            (double)sauronAltMsl)) {
        return false;
      }
    }

    if (!isnan(sauronHeading) &&
        !isinf(sauronHeading)) {

      if (!sauronAppend(
            n,
            ",\"heading_deg\":%.1f",
            (double)sauronHeading)) {
        return false;
      }
    }

    if (!isnan(sauronSpeedMps) &&
        !isinf(sauronSpeedMps)) {
      if (!sauronAppend(n, ",\"speed_mps\":%.1f",
                        (double)sauronSpeedMps)) {
        return false;
      }
    }

    if (sauronFix >= 0) {
      if (!sauronAppend(
            n,
            ",\"fix\":%d",
            sauronFix)) {
        return false;
      }
    }

    if (sauronSats >= 0) {
      if (!sauronAppend(
            n,
            ",\"sats\":%d",
            sauronSats)) {
        return false;
      }
    }

    if (!isnan(sauronHdop) &&
        !isinf(sauronHdop)) {

      if (!sauronAppend(
            n,
            ",\"hdop\":%.1f",
            (double)sauronHdop)) {
        return false;
      }
    }

    if (!sauronAppend(n, "}")) {
      return false;
    }
  }

  if (!isnan(sauronLaunchMsl) &&
      !isinf(sauronLaunchMsl)) {

    if (!sauronAppend(
          n,
          ",\"gps_alt_launch\":%.1f",
          (double)sauronLaunchMsl)) {
      return false;
    }
  }

  if (!sauronAppend(n, "}")) {
    return false;
  }

  return true;
}

// ============================================================
// INITIALISATIE
// ============================================================

static void sauronBegin() {
  if (sauronLive) {
    return;
  }

  sauronInitAttempted = true;
  sauronLastInitAttempt = millis();
  Serial.printf(
    "[sauron] MLX90640 initialiseren (SDA=%d, SCL=%d)...\n",
    SAURON_SDA,
    SAURON_SCL
  );

  // De bestaande camera blijft op zijn eigen pinconfiguratie.
  Wire.begin(SAURON_SDA, SAURON_SCL);
  Wire.setClock(400000);
  Wire.setTimeOut(100);

  Wire.beginTransmission(SAURON_I2C_ADDR);
  if (Wire.endTransmission() != 0) {
    Serial.println(
      "[sauron] MLX90640 NIET gevonden."
    );

    Serial.println(
      "[sauron] Controleer 3V3, GND, SDA GPIO47 en SCL GPIO48."
    );

    Serial.println(
      "[sauron] CameraWebServer blijft beschikbaar."
    );

    sauronError = "mlx90640_not_found";
    return;
  }

  uint16_t eeData[832];
  int status = MLX90640_DumpEE(SAURON_I2C_ADDR, eeData);
  if (status != 0) {
    Serial.printf("[sauron] EEPROM lezen mislukt (status %d).\n", status);
    sauronError = "mlx90640_eeprom_error";
    return;
  }

  status = MLX90640_ExtractParameters(eeData, &sauronMlx);
  if (status != 0) {
    Serial.printf("[sauron] Kalibratieparameters ongeldig (status %d).\n",
                  status);
    sauronError = "mlx90640_calibration_error";
    return;
  }

  status = MLX90640_SetRefreshRate(SAURON_I2C_ADDR, 0x05);
  if (status != 0) {
    Serial.printf("[sauron] Refresh rate instellen mislukt (status %d).\n",
                  status);
    sauronError = "mlx90640_configuration_error";
    return;
  }

  status = MLX90640_SetChessMode(SAURON_I2C_ADDR);
  if (status != 0) {
    Serial.printf("[sauron] Chess mode instellen mislukt (status %d).\n",
                  status);
    sauronError = "mlx90640_configuration_error";
    return;
  }

  // UDP-listener starten voor antwoorden van de laptop.
  if (!sauronUdp.begin(SAURON_UDP_POORT)) {
    Serial.println(
      "[sauron] Waarschuwing: UDP-poort kon niet worden gestart."
    );
  }

  sauronLive = true;
  sauronError = "ok";

  Serial.println(
    "[sauron] MLX90640 klaar."
  );

  Serial.println(
    "[sauron] Sensor: 32 x 24 pixels, refresh rate 8 Hz."
  );

  Serial.println(
    "[sauron] Dashboard-verzending: maximaal 1 frame/s."
  );
}

// ============================================================
// HOOFDLOOP
// ============================================================

static void sauronLoop() {
  if (!sauronLive) {
    if (!sauronInitAttempted ||
        millis() - sauronLastInitAttempt >= 5000UL) {
      sauronBegin();
    }
    return;
  }

  uint32_t nu = millis();

  if (nu - sauronLaatsteUitlezing < SAURON_READ_INTERVAL_MS) {
    return;
  }

  sauronLaatsteUitlezing = nu;

  // Lees op de sensor-refresh rate zodat /api/data steeds een recent frame
  // bevat, ook wanneer het externe dashboard tijdelijk niet bereikbaar is.
  int status = MLX90640_GetFrameData(SAURON_I2C_ADDR, sauronFrameData);
  if (status < 0) {
    sauronFrameErrors++;
    sauronError = "mlx90640_frame_error";
    Serial.println(
      "[sauron] Fout bij uitlezen van MLX90640-frame."
    );

    return;
  }

  const float ambientTemperature =
    MLX90640_GetTa(sauronFrameData, &sauronMlx);
  const float reflectedTemperature = ambientTemperature - 8.0f;
  MLX90640_CalculateTo(
    sauronFrameData,
    &sauronMlx,
    0.95f,
    reflectedTemperature,
    sauronRuw
  );

  sauronOmbouwen();

  if (!sauronBouwBody()) {
    Serial.println(
      "[sauron] JSON-buffer onvoldoende groot; frame overgeslagen."
    );

    return;
  }

  sauronFrameReady = true;

  if (nu - sauronLaatsteVerzending < SAURON_POST_INTERVAL_MS) {
    return;
  }

  sauronLaatsteVerzending = nu;

  // Zoek alleen opnieuw als nog geen dashboard-URL bekend is.
  if (sauronDoel.length() == 0) {
    if (!sauronVindDoel()) {
      return;
    }
  }

  HTTPClient http;
  http.setTimeout(1000);

  if (!http.begin(sauronDoel)) {
    Serial.println(
      "[sauron] HTTP-client kon niet worden gestart."
    );

    sauronDoel = "";
    return;
  }

  http.addHeader(
    "Content-Type",
    "application/json"
  );

  int code = http.POST(
    (uint8_t *)sauronBody,
    strlen(sauronBody)
  );

  http.end();

  if (code >= 200 && code < 300) {
    Serial.printf(
      "[sauron] Frame verzonden (HTTP %d).\n",
      code
    );

  } else {
    Serial.printf(
      "[sauron] Verzenden mislukt (HTTP %d); opnieuw zoeken.\n",
      code
    );

    sauronDoel = "";
  }
}

// ============================================================
// GPS-API
// ============================================================

static void sauronSetGps(
  float lat,
  float lon,
  float altMsl,
  float heading,
  float speedMps,
  int fix,
  int sats,
  float hdop
) {
  sauronLat = lat;
  sauronLon = lon;
  sauronAltMsl = altMsl;
  sauronHeading = heading;
  sauronSpeedMps = speedMps;
  sauronFix = fix;
  sauronSats = sats;
  sauronHdop = hdop;
}

// Lanceerhoogte in meters boven zeeniveau.
// Alleen aanroepen als deze waarde daadwerkelijk bekend is.
static void sauronSetLaunchMsl(float altMsl) {
  sauronLaunchMsl = altMsl;
}

static bool sauronActief() {
  return sauronLive;
}

static bool sauronHeeftFrame() {
  return sauronFrameReady;
}

static const char *sauronLaatsteJson() {
  if (sauronFrameReady) {
    return sauronBody;
  }

  static const char unavailable[] =
    "{\"frame\":null,\"thermal_available\":false}";
  return unavailable;
}

static const char *sauronLaatsteGpsJson(bool dataSeen) {
  static char json[320];
  const bool locationValid =
    isfinite(sauronLat) && isfinite(sauronLon);
  const int length = snprintf(
    json,
    sizeof(json),
    "{\"data_seen\":%s,\"location_valid\":%s,\"lat\":%s,\"lon\":%s,"
    "\"alt_msl\":%s,\"heading_deg\":%s,\"speed_mps\":%s,"
    "\"fix\":%d,\"sats\":%d,\"hdop\":%s}",
    dataSeen ? "true" : "false",
    locationValid ? "true" : "false",
    isfinite(sauronLat) ? String(sauronLat, 6).c_str() : "null",
    isfinite(sauronLon) ? String(sauronLon, 6).c_str() : "null",
    isfinite(sauronAltMsl) ? String(sauronAltMsl, 1).c_str() : "null",
    isfinite(sauronHeading) ? String(sauronHeading, 1).c_str() : "null",
    isfinite(sauronSpeedMps) ? String(sauronSpeedMps, 1).c_str() : "null",
    sauronFix,
    sauronSats,
    isfinite(sauronHdop) ? String(sauronHdop, 1).c_str() : "null");

  if (length < 0 || static_cast<size_t>(length) >= sizeof(json)) {
    return nullptr;
  }
  return json;
}

static const char *sauronStatus() {
  return sauronError;
}

static uint32_t sauronFrameErrorCount() {
  return sauronFrameErrors;
}
