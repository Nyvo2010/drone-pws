"""Brand-tracking over frames: één brand = één record, ook als hij wegvalt.

De pipeline is per frame stateless. Zonder tracking zou dezelfde brand bij
elke frame een nieuwe vermelding worden, en een brand die even buiten beeld
valt zou verdwijnen en later als "nieuwe" brand terugkomen. Deze module
houdt daarom een track per brand bij:

- **Matchen** gebeurt op wereldcoördinaten (binnen `track_match_radius_m`).
  Zonder geldige locatie (AGL <= 0) of als de geo-afstand te groot is,
  valt hij terug op pixelafstand (stabiel bij jitter van de heetste pixel).
- **Uit beeld** = geen detectie meer, maar pas na `track_lost_after_s`
  gemarkeerd (korte dropout flikkert niet). `last_seen` blijft staan.
- **Terug in beeld** binnen `track_archive_after_s` hergebruikt dezelfde
  track en dus hetzelfde ID; er komt geen duplicaat bij.
- **Archiveren** verwijdert de track pas na `track_archive_after_s` uit het
  live-overzicht. De volledige historie staat in het vluchtbestand.

Bewuste beperking (YAGNI): splitst één brand in twee losse blobs, dan
worden dat twee tracks. Samenvoegen zou twee echte branden naast elkaar
kunnen samenvoegen; dat is erger dan een extra vermelding.
"""

import math
import time
from dataclasses import dataclass, field

from .config import DEFAULT, Config


@dataclass
class Track:
    """Interne staat van één brand; `det` is de laatste detectie."""

    id: int
    first_seen: float
    last_seen: float
    observations: int
    lost: bool
    det: dict = field(default_factory=dict)

    def to_dict(self, now, lost_after_s):
        """JSON-klare snapshot met alles wat de UI en het logbestand nodig hebben."""
        data = dict(self.det)
        active = (now - self.last_seen) <= lost_after_s
        data.update({
            "id": "B%d" % self.id,
            "status": "active" if active else "lost",
            "active": active,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "observations": self.observations,
        })
        return data


def _distance_m(lat1, lon1, lat2, lon2):
    """Korte-afstand-benadering (platte aarde), ruim genoeg voor < 1 km."""
    mid = math.radians((lat1 + lat2) / 2.0)
    dlat = (lat2 - lat1) * 111320.0
    dlon = (lon2 - lon1) * 111320.0 * math.cos(mid)
    return math.hypot(dlat, dlon)


class FireTracker:
    """Houdt tracks bij en levert per frame een gesorteerde snapshot + events."""

    def __init__(self, cfg=DEFAULT):
        if not isinstance(cfg, Config):
            raise TypeError("cfg moet een Config zijn")
        self.cfg = cfg
        self._tracks = {}
        self._next_id = 1

    def reset(self):
        """Begin een nieuwe vlucht: IDs beginnen weer bij B1."""
        self._tracks = {}
        self._next_id = 1

    def _match(self, track, det):
        """Afstand tussen track en detectie, of None als ze niet matchen.

        Retourneert (soort, waarde) met soort 0 = meters, 1 = pixels. Een
        geo-match heeft voorrang op een pixel-match.
        """
        tlat, tlon = track.det.get("hotspot_lat"), track.det.get("hotspot_lon")
        dlat, dlon = det.get("hotspot_lat"), det.get("hotspot_lon")
        if None not in (tlat, tlon, dlat, dlon):
            dist = _distance_m(tlat, tlon, dlat, dlon)
            if dist <= self.cfg.track_match_radius_m:
                return (0, dist)
            # Geo wijkt te ver af (bijv. heetste pixel verspringt binnen
            # een grote brand). Probeer hieronder alsnog de pixelafstand.

        tx, ty = track.det.get("x"), track.det.get("y")
        dx, dy = det.get("x"), det.get("y")
        if None not in (tx, ty, dx, dy):
            dist = math.hypot(tx - dx, ty - dy)
            if dist <= self.cfg.track_pixel_radius:
                return (1, dist)
        return None

    def update(self, fires, now=None):
        """Verwerk één frame.

        `fires` = geclassificeerde branden van pipeline.detect_event (met
        optioneel hotspot_lat/lon en x/y). Retourneert
        (snapshot, events) waarbij events new/lost/reacquired/archived zijn.
        """
        now = time.time() if now is None else float(now)
        events = []

        # Alle mogelijke matches, dichtstbij eerst. Zo kan één track nooit
        # twee detecties opslokken en andersom.
        pairs = []
        for track_id, track in self._tracks.items():
            for det_index, det in enumerate(fires):
                match = self._match(track, det)
                if match is not None:
                    pairs.append((match[0], match[1], track_id, det_index))
        pairs.sort(key=lambda p: (p[0], p[1]))

        matched_tracks = set()
        matched_dets = set()
        for _, _, track_id, det_index in pairs:
            if track_id in matched_tracks or det_index in matched_dets:
                continue
            matched_tracks.add(track_id)
            matched_dets.add(det_index)
            track = self._tracks[track_id]
            was_lost = track.lost
            track.det = dict(fires[det_index])
            track.last_seen = now
            track.observations += 1
            track.lost = False
            if was_lost:
                events.append({"type": "reacquired",
                               "fire": track.to_dict(now, self.cfg.track_lost_after_s)})

        # Nieuwe detecties zonder track worden een nieuwe brand.
        for det_index, det in enumerate(fires):
            if det_index in matched_dets:
                continue
            track = Track(
                id=self._next_id,
                first_seen=now,
                last_seen=now,
                observations=1,
                lost=False,
                det=dict(det),
            )
            self._tracks[track.id] = track
            self._next_id += 1
            events.append({"type": "new",
                           "fire": track.to_dict(now, self.cfg.track_lost_after_s)})

        # Niet gezien: na de grace-periode "uit beeld", daarna archiveren.
        for track_id, track in list(self._tracks.items()):
            if track_id in matched_tracks:
                continue
            stil = now - track.last_seen
            if not track.lost and stil > self.cfg.track_lost_after_s:
                track.lost = True
                events.append({"type": "lost",
                               "fire": track.to_dict(now, self.cfg.track_lost_after_s)})
            if stil > self.cfg.track_archive_after_s:
                events.append({"type": "archived",
                               "fire": track.to_dict(now, self.cfg.track_lost_after_s)})
                del self._tracks[track_id]

        return self.snapshot(now), events

    def snapshot(self, now=None):
        """Actieve tracks eerst, daarna de laatst geziene; JSON-klaar."""
        now = time.time() if now is None else float(now)
        tracks = [
            t.to_dict(now, self.cfg.track_lost_after_s)
            for t in self._tracks.values()
            if now - t.last_seen <= self.cfg.track_archive_after_s
        ]
        tracks.sort(key=lambda f: (not f["active"], -f["last_seen"], f["id"]))
        return tracks

