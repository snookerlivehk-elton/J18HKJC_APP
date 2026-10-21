import 'package:j18pro_racecard/data/jjjc_api_config.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

const jjjcRacecardSchema = 'jjjc.racecard.v1';
const jjjcResultsSchema = 'jjjc.results.v1';

const _venueCap = {'HV': 12, 'ST': 14};

const _poolLabels = {
  'WIN': '獨贏',
  'PLACE': '位置',
  'QUINELLA': '連贏',
  'QUINELLA PLACE': '位置Q',
  'FORECAST': '二重彩',
  'TIERCE': '單T',
  'TRIO': '三重彩',
  'FIRST 4': '四連環',
  'QUARTET': '四重彩',
};

/// HKJC silk CDN (or `J18_SILK_BASE`). Null when [code] is not a brand.
String? silkUrlForHorseCode(String? code, {String? base}) {
  final trimmed = (code ?? '').trim();
  if (!RegExp(r'^[A-Za-z0-9]+$').hasMatch(trimmed)) return null;
  final root = (base ?? JjjcApiConfig.defaultSilkCdnBase).replaceAll(
    RegExp(r'/+$'),
    '',
  );
  return '$root/$trimmed.gif';
}

/// Joins `jjjc.racecard.v1` and `jjjc.results.v1` on `race_no` + `horse_no`.
///
/// Chinese racecard names win over English results names. `win_odds` fills
/// 獨贏. The catalog's `live_odds` product has no export path, so 位置 stays
/// empty. HV drops horse numbers above 12; ST drops numbers above 14.
Meeting mapJjjcMeeting({
  required String date,
  required String venue,
  Map<String, dynamic>? racecard,
  Map<String, dynamic>? results,
  String? silkBase,
}) {
  _rejectBad(racecard, jjjcRacecardSchema);
  _rejectBad(results, jjjcResultsSchema);
  final course = venue.toUpperCase();
  final races = <int, _RaceBuild>{};
  if (racecard != null) {
    for (final race in _raceList(racecard)) {
      final num = _raceNo(race);
      if (num == null) continue;
      races[num] = _raceFromCard(race, num, course, silkBase);
    }
  }
  if (results != null) {
    for (final race in _raceList(results)) {
      final num = _raceNo(race);
      if (num == null) continue;
      final slot = races.putIfAbsent(
        num,
        () => _raceFromCard(race, num, course, silkBase),
      );
      _mergeResults(slot, race, course, silkBase);
    }
  }
  final built = races.values.toList()..sort((a, b) => a.num.compareTo(b.num));
  if (built.isEmpty) return _emptyMeeting(date, course);
  final parts = date.split('-');
  return Meeting(
    date: date,
    y: parts.isNotEmpty ? parts[0] : '',
    m: parts.length > 1 ? parts[1] : '',
    d: parts.length > 2 ? parts[2] : '',
    weekday: _weekday(date),
    courseLabel: courseLabelOf(course),
    source: 'jjjc.racecard.v1 + jjjc.results.v1',
    races: [for (final race in built) race.toRace()],
  );
}

Meeting _emptyMeeting(String date, String course) {
  final parts = date.split('-');
  return Meeting(
    date: date,
    y: parts.isNotEmpty ? parts[0] : '',
    m: parts.length > 1 ? parts[1] : '',
    d: parts.length > 2 ? parts[2] : '',
    weekday: _weekday(date),
    courseLabel: courseLabelOf(course),
    source: 'jjjc empty',
    races: [
      Race(num: 1, name: '該日暫無賽事', time: '', meta: '該日暫無賽事', runners: const []),
    ],
  );
}

void _rejectBad(Map<String, dynamic>? payload, String schema) {
  if (payload == null) return;
  final declared = payload['schema'];
  if (declared is String && declared.isNotEmpty && declared != schema) {
    throw RaceLoadException('賽事資料格式不符');
  }
  final status = payload['status'];
  if (status is String && status.toLowerCase() == 'unavailable') {
    throw RaceLoadException('伺服器暫時未能提供賽事');
  }
}

List<Map<String, dynamic>> _raceList(Map<String, dynamic> payload) {
  final raw = payload['races'];
  if (raw == null) return const [];
  if (raw is! List) throw RaceLoadException('賽事資料格式不符');
  return [
    for (final item in raw)
      if (item is Map) Map<String, dynamic>.from(item),
  ];
}

class _RaceBuild {
  _RaceBuild({
    required this.num,
    required this.name,
    required this.time,
    required this.meta,
  });

  final int num;
  String name;
  String time;
  String meta;
  final runners = <int, Runner>{};
  final dividends = <RaceDividend>[];

  Race toRace() {
    final rows = runners.values.toList()..sort((a, b) => a.no.compareTo(b.no));
    final hasPay = dividends.any((row) => row.pay != null);
    final hasFinish = rows.any((row) => row.finish != null);
    return Race(
      num: num,
      name: name,
      time: time,
      meta: meta,
      runners: rows,
      paid: hasFinish || hasPay,
      payoutReady: hasPay,
      hasDividend: hasPay,
      dividends: dividends.isEmpty ? null : dividends,
    );
  }
}

_RaceBuild _raceFromCard(
  Map<String, dynamic> race,
  int num,
  String venue,
  String? silkBase,
) {
  final name = _preferZh([
    race['race_name_ch'],
    race['race_name'],
    race['race_name_en'],
  ], fallback: '第$num場');
  final time = _clock(race['post_time']);
  final built = _RaceBuild(
    num: num,
    name: name,
    time: time,
    meta: _meta(time, name, race),
  );
  for (final runner in _runnerList(race)) {
    final horse = _horseNo(runner);
    if (horse == null || !_horseAllowed(horse, venue) || _placeholder(runner)) {
      continue;
    }
    built.runners[horse] = _runnerFrom(runner, horse, silkBase);
  }
  return built;
}

void _mergeResults(
  _RaceBuild slot,
  Map<String, dynamic> race,
  String venue,
  String? silkBase,
) {
  if (slot.name == '第${slot.num}場') {
    slot.name = _preferZh([
      race['race_name_ch'],
      race['race_name'],
      race['race_name_en'],
    ], fallback: slot.name);
    slot.meta = _meta(slot.time, slot.name, race);
  }
  for (final runner in _runnerList(race)) {
    final horse = _horseNo(runner);
    if (horse == null || !_horseAllowed(horse, venue) || _placeholder(runner)) {
      continue;
    }
    final incoming = _runnerFrom(runner, horse, silkBase);
    final current = slot.runners[horse];
    if (current == null) {
      slot.runners[horse] = incoming;
      continue;
    }
    slot.runners[horse] = Runner(
      no: current.no,
      name: _keepZh(current.name, incoming.name),
      draw: current.draw != 0 ? current.draw : incoming.draw,
      jockey: _keepZh(current.jockey, incoming.jockey),
      trainer: _keepZh(current.trainer, incoming.trainer),
      win: incoming.win ?? current.win,
      place: current.place,
      scratched: current.scratched || incoming.scratched,
      silk: current.silk ?? incoming.silk,
      form6: current.form6 ?? incoming.form6,
      recent: current.recent ?? incoming.recent,
      age: current.age ?? incoming.age,
      rating: current.rating ?? incoming.rating,
      rtgDelta: current.rtgDelta ?? incoming.rtgDelta,
      hw: current.hw ?? incoming.hw,
      bodyWt: current.bodyWt ?? incoming.bodyWt,
      gear: current.gear ?? incoming.gear,
      career: current.career,
      rail: current.rail,
      dam: current.dam,
      sire: current.sire,
      damsire: current.damsire,
      owner: current.owner,
      prize: current.prize,
      finish: incoming.finish ?? current.finish,
      position: incoming.position ?? current.position,
    );
  }
  final raw = race['dividends'];
  if (raw is! List) return;
  for (final item in raw) {
    if (item is! Map) continue;
    final pool = item['pool'];
    if (pool is! String || pool.isEmpty || pool.toLowerCase() == 'pool') {
      continue;
    }
    final combo = item['combination'] ?? item['combo'];
    slot.dividends.add(
      RaceDividend(
        pool: _poolLabels[pool] ?? pool,
        combo: combo == null ? '—' : '$combo',
        pay: _asNum(item['amount'] ?? item['pay']),
      ),
    );
  }
}

Runner _runnerFrom(Map<String, dynamic> row, int horse, String? silkBase) {
  final code = _optText(row['horse_code']);
  final delta = row['rating_delta'];
  return Runner(
    no: horse,
    name: _preferZh([
      row['horse_name_ch'],
      row['horse_name'],
      row['horseNameCh'],
      row['horse_name_en'],
    ], fallback: '馬$horse'),
    draw: _asInt(row['draw']) ?? 0,
    jockey: _preferZh([
      row['jockey_name_ch'],
      row['jockey_name'],
      row['jockeyNameCh'],
      row['jockey_name_en'],
    ]),
    trainer: _preferZh([
      row['trainer_name_ch'],
      row['trainer_name'],
      row['trainerNameCh'],
      row['trainer_name_en'],
    ]),
    win: _asNum(row['win_odds'])?.toDouble(),
    place: null,
    scratched: row['scratched'] == true,
    silk: silkUrlForHorseCode(code, base: silkBase),
    form6: _optText(row['last_six_run']),
    recent: _optText(row['last_six_run']),
    age: null,
    rating: _asInt(row['rating']),
    rtgDelta: delta == null ? null : '$delta',
    hw: _asInt(row['handicap_weight'] ?? row['actual_weight']),
    bodyWt: _asInt(row['horse_weight'] ?? row['declared_horse_weight']),
    gear: _optText(row['gear']),
    career: null,
    rail: null,
    dam: null,
    sire: null,
    damsire: null,
    owner: null,
    prize: null,
    finish: _asInt(row['finish_order_num']),
    position: _asInt(row['finishing_position']),
  );
}

List<Map<String, dynamic>> _runnerList(Map<String, dynamic> race) {
  final raw = race['runners'];
  if (raw is! List) return const [];
  return [
    for (final item in raw)
      if (item is Map) Map<String, dynamic>.from(item),
  ];
}

int? _raceNo(Map<String, dynamic> race) {
  final direct = _asInt(race['race_no']);
  if (direct != null) return direct;
  final id = race['race_id'];
  if (id is String && id.length >= 2) {
    return int.tryParse(id.substring(id.length - 2));
  }
  return null;
}

int? _horseNo(Map<String, dynamic> row) {
  for (final key in ['horse_no', 'runner_no', 'horseNo', 'runnerNo', 'no']) {
    final value = _asInt(row[key]);
    if (value != null) return value;
  }
  return null;
}

bool _horseAllowed(int horse, String venue) {
  if (horse < 1) return false;
  final cap = _venueCap[venue];
  if (cap == null) return true;
  return horse <= cap;
}

bool _placeholder(Map<String, dynamic> row) {
  return row['energy_is_placeholder'] == true || row['is_placeholder'] == true;
}

String _keepZh(String current, String incoming) {
  if (current.isEmpty) return incoming;
  if (!_looksLatin(current)) return current;
  if (incoming.isNotEmpty && !_looksLatin(incoming)) return incoming;
  return current;
}

String _preferZh(List<Object?> candidates, {String fallback = ''}) {
  final nonempty = <String>[];
  for (final candidate in candidates) {
    final text = _optText(candidate);
    if (text == null) continue;
    nonempty.add(text);
    if (!_looksLatin(text)) return text;
  }
  if (nonempty.isNotEmpty) return nonempty.first;
  return fallback;
}

bool _looksLatin(String text) {
  return !RegExp(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]').hasMatch(text);
}

String? _optText(Object? value) {
  if (value == null) return null;
  final text = '$value'.trim();
  if (text.isEmpty || text == '-' || text.toLowerCase() == 'none') return null;
  if (text.toLowerCase() == 'null') return null;
  return text;
}

int? _asInt(Object? value) {
  if (value == null || value == '') return null;
  if (value is int) return value;
  if (value is num && value == value.roundToDouble()) return value.toInt();
  return int.tryParse('$value'.trim());
}

num? _asNum(Object? value) {
  if (value == null || value == '') return null;
  if (value is num) return value;
  return num.tryParse('$value'.trim().replaceAll(',', ''));
}

String _clock(Object? value) {
  final text = _optText(value);
  if (text == null) return '';
  final match = RegExp(r'T(\d{2}):(\d{2})').firstMatch(text);
  if (match == null) return '';
  return '${match.group(1)}:${match.group(2)}';
}

String _meta(String time, String name, Map<String, dynamic> race) {
  final distance = _asInt(race['distance_m']);
  final parts = <String>[
    if (time.isNotEmpty) time,
    if (name.isNotEmpty) name,
    if (_optText(race['track']) != null) _optText(race['track'])!,
    if (_optText(race['surface']) != null) _optText(race['surface'])!,
    if (distance != null) '$distance米',
    if (_optText(race['race_class_ch'] ?? race['race_class']) != null)
      _optText(race['race_class_ch'] ?? race['race_class'])!,
    if (_optText(race['ground'] ?? race['going']) != null)
      _optText(race['ground'] ?? race['going'])!,
  ];
  return parts.join(' ');
}

String _weekday(String iso) {
  final parts = iso.split('-');
  if (parts.length != 3) return '';
  final y = int.tryParse(parts[0]);
  final m = int.tryParse(parts[1]);
  final d = int.tryParse(parts[2]);
  if (y == null || m == null || d == null) return '';
  return weekdayShort(DateTime(y, m, d));
}
