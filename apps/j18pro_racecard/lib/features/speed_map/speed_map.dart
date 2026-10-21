import 'dart:convert';
import 'dart:typed_data';

/// HKJC SpeedPro for the meeting the site currently publishes.
///
/// Web `SPEEDMAP_CMS`. The path is `current`, so the chart follows HKJC's
/// live meeting, not the racecard date selected in this app.
const kSpeedMapBase =
    'https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/sg_race_';

/// Matches the live response `Cache-Control: public, max-age=600`.
///
/// Web keeps `speedMapCache` for the page session and never expires it.
/// This app drops an entry after ten minutes so a later open refetches.
const speedMapCacheTtl = Duration(minutes: 10);

/// Why a chart could not be shown. Failures are not written to the cache.
enum SpeedMapFailure {
  /// Transport error, non-2xx, or a body that is not JSON.
  ///
  /// Copy: 暫未能載入走位圖，請稍後再試. Web uses this for every `fetch` rejection,
  /// including a missing RaceMap.
  offline,

  /// JSON parsed, but `RaceMap` is missing, not a `data:image`, or not base64.
  ///
  /// Copy: 此場暫無走位圖. Web's image renderer uses this sentence; its fetch
  /// path throws `"no RaceMap"` and shows the retry sentence instead.
  noChart,
}

class SpeedMapException implements Exception {
  const SpeedMapException.offline() : kind = SpeedMapFailure.offline;

  const SpeedMapException.noChart() : kind = SpeedMapFailure.noChart;

  final SpeedMapFailure kind;

  @override
  String toString() => kind.name;
}

/// One decoded RaceMap plus the zh-HK (or en-US) info line.
class SpeedMapChart {
  const SpeedMapChart({
    required this.bytes,
    required this.course,
    required this.distance,
    required this.raceName,
    required this.date,
  });

  final Uint8List bytes;
  final String course;
  final String distance;
  final String raceName;
  final String date;

  /// Web `speedMapMetaText`: 第N場, then course, distance, name, date.
  String metaFor(int raceNo) {
    final bits = <String>['第$raceNo場'];
    if (course.isNotEmpty) bits.add(course);
    if (distance.isNotEmpty) bits.add(distance);
    if (raceName.isNotEmpty) bits.add(raceName);
    if (date.isNotEmpty) bits.add(date);
    return bits.join(' · ');
  }
}

Uri speedMapUri(int raceNum) => Uri.parse('$kSpeedMapBase$raceNum');

/// Strips a leading UTF-8 BOM. HKJC's JSON starts with U+FEFF, and
/// `jsonDecode` rejects that character.
String stripSpeedMapBom(String body) {
  if (body.isEmpty) return body;
  if (body.codeUnitAt(0) == 0xFEFF) return body.substring(1);
  return body;
}

/// Decodes a `data:image/...;base64,` URL. Returns null when it is not one.
Uint8List? decodeDataImage(String dataUrl) {
  if (!dataUrl.startsWith('data:image')) return null;
  final comma = dataUrl.indexOf(',');
  if (comma < 0) return null;
  if (!dataUrl.substring(0, comma).contains('base64')) return null;
  try {
    final bytes = base64Decode(dataUrl.substring(comma + 1));
    if (bytes.isEmpty) return null;
    return bytes;
  } on FormatException {
    return null;
  }
}

/// Web `fetchSpeedMap` payload rules.
///
/// `zh-hk` wins as a whole block when it is present, even if its map is
/// empty. `en-us` is used only when `zh-hk` is absent. Info is
/// `RaceInfoChi`, then `RaceInfoEng`.
///
/// Throws [FormatException] when [body] is not JSON (caller maps that to
/// [SpeedMapFailure.offline]). Throws [SpeedMapException.noChart] when the
/// JSON has no usable RaceMap.
SpeedMapChart parseSpeedMap(String body) {
  final decoded = jsonDecode(stripSpeedMapBom(body));
  if (decoded is! Map) {
    throw const SpeedMapException.noChart();
  }
  final block = decoded['zh-hk'] ?? decoded['en-us'];
  if (block is! Map) {
    throw const SpeedMapException.noChart();
  }
  final map = block['RaceMap']?.toString() ?? '';
  final bytes = decodeDataImage(map);
  if (bytes == null) {
    throw const SpeedMapException.noChart();
  }
  final infoRaw = block['RaceInfoChi'] ?? block['RaceInfoEng'];
  final info = infoRaw is Map ? infoRaw : const <String, Object?>{};
  return SpeedMapChart(
    bytes: bytes,
    course: _text(info['Racecourse']),
    distance: _text(info['Distance']),
    raceName: _text(info['RaceName']),
    date: _text(info['Date']),
  );
}

String _text(Object? value) {
  if (value == null) return '';
  return value.toString();
}

class _SpeedMapEntry {
  const _SpeedMapEntry(this.chart, this.at);

  final SpeedMapChart chart;
  final DateTime at;
}

/// In-memory cache keyed by race number only, matching Web `speedMapCache`.
///
/// RaceMap is a data-URL PNG and changes with the current meeting, so it is
/// not written to SharedPreferences. A stale day would otherwise stick.
class SpeedMapCache {
  SpeedMapCache({DateTime Function()? clock}) : _clock = clock ?? DateTime.now;

  final DateTime Function() _clock;
  final Map<int, _SpeedMapEntry> _entries = {};

  SpeedMapChart? get(int raceNum) {
    final entry = _entries[raceNum];
    if (entry == null) return null;
    if (_clock().difference(entry.at) >= speedMapCacheTtl) {
      _entries.remove(raceNum);
      return null;
    }
    return entry.chart;
  }

  void put(int raceNum, SpeedMapChart chart) {
    _entries[raceNum] = _SpeedMapEntry(chart, _clock());
  }
}
