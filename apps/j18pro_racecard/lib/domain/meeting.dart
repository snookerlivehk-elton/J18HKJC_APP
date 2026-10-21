import 'package:flutter/foundation.dart';

/// Immutable racecard snapshot aligned with Web `MEETING`.
@immutable
class Meeting {
  Meeting({
    required this.date,
    required this.y,
    required this.m,
    required this.d,
    required this.weekday,
    required this.courseLabel,
    required this.source,
    required List<Race> races,
  }) : races = List.unmodifiable(races);

  final String date;
  final String y;
  final String m;
  final String d;
  final String weekday;
  final String courseLabel;
  final String? source;
  final List<Race> races;

  Race? raceByNum(int num) {
    for (final race in races) {
      if (race.num == num) return race;
    }
    return null;
  }

  /// Replaces the race with the same [Race.num]. Other races stay as they are.
  Meeting replaceRace(Race race) {
    return Meeting(
      date: date,
      y: y,
      m: m,
      d: d,
      weekday: weekday,
      courseLabel: courseLabel,
      source: source,
      races: [
        for (final item in races)
          if (item.num == race.num) race else item,
      ],
    );
  }

  factory Meeting.fromJson(Map<String, dynamic> json) {
    final rawRaces = json['races'];
    if (rawRaces is! List) {
      throw FormatException('欄位 races 無法解析');
    }
    return Meeting(
      date: _reqString(json, 'date'),
      y: _reqString(json, 'y'),
      m: _reqString(json, 'm'),
      d: _reqString(json, 'd'),
      weekday: _reqString(json, 'weekday'),
      courseLabel: _reqString(json, 'courseLabel'),
      source: _optString(json, 'source'),
      races: [
        for (final item in rawRaces)
          Race.fromJson(Map<String, dynamic>.from(item as Map)),
      ],
    );
  }

  @override
  bool operator ==(Object other) {
    return other is Meeting &&
        date == other.date &&
        y == other.y &&
        m == other.m &&
        d == other.d &&
        weekday == other.weekday &&
        courseLabel == other.courseLabel &&
        source == other.source &&
        listEquals(races, other.races);
  }

  @override
  int get hashCode => Object.hash(
    date,
    y,
    m,
    d,
    weekday,
    courseLabel,
    source,
    Object.hashAll(races),
  );
}

/// One dividend row. Web `race.dividends[]` uses `pool` / `combo` / `pay`.
@immutable
class RaceDividend {
  const RaceDividend({
    required this.pool,
    required this.combo,
    required this.pay,
  });

  final String pool;
  final String combo;
  final num? pay;

  factory RaceDividend.fromJson(Map<String, dynamic> json) {
    final pool = json['pool'];
    if (pool is! String || pool.isEmpty) {
      throw FormatException('欄位 pool 無法解析');
    }
    final comboRaw = json.containsKey('combo')
        ? json['combo']
        : json['combination'];
    if (comboRaw != null && comboRaw is! String && comboRaw is! num) {
      throw FormatException('欄位 combo 無法解析');
    }
    final payRaw = json.containsKey('pay') ? json['pay'] : json['dividend'];
    if (payRaw != null && payRaw is! num) {
      throw FormatException('欄位 pay 無法解析');
    }
    return RaceDividend(
      pool: pool,
      combo: comboRaw == null ? '—' : '$comboRaw',
      pay: payRaw as num?,
    );
  }

  @override
  bool operator ==(Object other) {
    return other is RaceDividend &&
        pool == other.pool &&
        combo == other.combo &&
        pay == other.pay;
  }

  @override
  int get hashCode => Object.hash(pool, combo, pay);
}

@immutable
class Race {
  Race({
    required this.num,
    required this.name,
    required this.time,
    required this.meta,
    required List<Runner> runners,
    this.paid = false,
    this.payoutReady = false,
    this.hasDividend = false,
    List<RaceDividend>? dividends,
  }) : runners = List.unmodifiable(runners),
       dividends = dividends == null ? null : List.unmodifiable(dividends);

  final int num;
  final String name;
  final String time;
  final String meta;
  final List<Runner> runners;

  /// Web `race.paid`. Absent in the demo fixture, so races stay 未派彩.
  final bool paid;

  /// Web `race.payoutReady`.
  final bool payoutReady;

  /// Web `race.hasDividend`.
  final bool hasDividend;

  /// Web `race.dividends`. Null when the key is absent.
  final List<RaceDividend>? dividends;

  Race copyWith({
    bool? paid,
    bool? payoutReady,
    bool? hasDividend,
    List<RaceDividend>? dividends,
  }) {
    return Race(
      num: num,
      name: name,
      time: time,
      meta: meta,
      runners: runners,
      paid: paid ?? this.paid,
      payoutReady: payoutReady ?? this.payoutReady,
      hasDividend: hasDividend ?? this.hasDividend,
      dividends: dividends ?? this.dividends,
    );
  }

  /// Dropdown label. Not the Phase 2 race-pill control.
  String get selectorLabel => '第$num場 $name';

  factory Race.fromJson(Map<String, dynamic> json) {
    final rawRunners = json['runners'];
    if (rawRunners is! List) {
      throw FormatException('欄位 runners 無法解析');
    }
    return Race(
      num: _reqInt(json, 'num'),
      name: _reqString(json, 'name'),
      time: _reqString(json, 'time'),
      meta: _reqString(json, 'meta'),
      runners: [
        for (final item in rawRunners)
          Runner.fromJson(Map<String, dynamic>.from(item as Map)),
      ],
      paid: _optBool(json, 'paid') ?? false,
      payoutReady: _optBool(json, 'payoutReady') ?? false,
      hasDividend: _optBool(json, 'hasDividend') ?? false,
      dividends: _optDividends(json),
    );
  }

  @override
  bool operator ==(Object other) {
    return other is Race &&
        num == other.num &&
        name == other.name &&
        time == other.time &&
        meta == other.meta &&
        paid == other.paid &&
        payoutReady == other.payoutReady &&
        hasDividend == other.hasDividend &&
        listEquals(runners, other.runners) &&
        listEquals(dividends, other.dividends);
  }

  @override
  int get hashCode => Object.hash(
    num,
    name,
    time,
    meta,
    paid,
    payoutReady,
    hasDividend,
    Object.hashAll(runners),
    dividends == null ? null : Object.hashAll(dividends!),
  );
}

/// One horse. Starred Web fields are required; the rest of the snapshot is kept.
@immutable
class Runner {
  const Runner({
    required this.no,
    required this.name,
    required this.draw,
    required this.jockey,
    required this.trainer,
    required this.win,
    required this.place,
    required this.scratched,
    required this.silk,
    required this.form6,
    required this.recent,
    required this.age,
    required this.rating,
    required this.rtgDelta,
    required this.hw,
    required this.bodyWt,
    required this.gear,
    required this.career,
    required this.rail,
    required this.dam,
    required this.sire,
    required this.damsire,
    required this.owner,
    required this.prize,
    this.finish,
    this.position,
    this.rank,
    this.placePos,
  });

  final int no;
  final String name;
  final int draw;
  final String jockey;
  final String trainer;
  final double? win;
  final double? place;
  final bool scratched;
  final String? silk;
  final String? form6;
  final String? recent;
  final int? age;
  final int? rating;
  final String? rtgDelta;
  final int? hw;
  final int? bodyWt;
  final String? gear;
  final String? career;
  final String? rail;
  final String? dam;
  final String? sire;
  final String? damsire;
  final String? owner;
  final String? prize;

  /// Official finishing order when the snapshot has one. Demo races leave these null.
  final int? finish;
  final int? position;
  final int? rank;
  final int? placePos;

  factory Runner.fromJson(Map<String, dynamic> json) {
    return Runner(
      no: _reqInt(json, 'no'),
      name: _reqString(json, 'name'),
      draw: _reqInt(json, 'draw'),
      jockey: _reqString(json, 'jockey'),
      trainer: _reqString(json, 'trainer'),
      win: _optOdds(json, 'win'),
      place: _optOdds(json, 'place'),
      scratched: _optBool(json, 'scratched') ?? false,
      silk: _optString(json, 'silk'),
      form6: _optString(json, 'form6'),
      recent: _optString(json, 'recent'),
      age: _optInt(json, 'age'),
      rating: _optInt(json, 'rating'),
      rtgDelta: _optString(json, 'rtgDelta'),
      hw: _optInt(json, 'hw'),
      bodyWt: _optInt(json, 'bodyWt'),
      gear: _optString(json, 'gear'),
      career: _optString(json, 'career'),
      rail: _optString(json, 'rail'),
      dam: _optString(json, 'dam'),
      sire: _optString(json, 'sire'),
      damsire: _optString(json, 'damsire'),
      owner: _optString(json, 'owner'),
      prize: _optString(json, 'prize'),
      finish: _optInt(json, 'finish'),
      position: _optInt(json, 'position'),
      rank: _optInt(json, 'rank'),
      placePos: _optInt(json, 'placePos'),
    );
  }

  @override
  bool operator ==(Object other) {
    return other is Runner &&
        no == other.no &&
        name == other.name &&
        draw == other.draw &&
        jockey == other.jockey &&
        trainer == other.trainer &&
        win == other.win &&
        place == other.place &&
        scratched == other.scratched &&
        silk == other.silk &&
        form6 == other.form6 &&
        recent == other.recent &&
        age == other.age &&
        rating == other.rating &&
        rtgDelta == other.rtgDelta &&
        hw == other.hw &&
        bodyWt == other.bodyWt &&
        gear == other.gear &&
        career == other.career &&
        rail == other.rail &&
        dam == other.dam &&
        sire == other.sire &&
        damsire == other.damsire &&
        owner == other.owner &&
        prize == other.prize &&
        finish == other.finish &&
        position == other.position &&
        rank == other.rank &&
        placePos == other.placePos;
  }

  @override
  int get hashCode => Object.hashAll([
    no,
    name,
    draw,
    jockey,
    trainer,
    win,
    place,
    scratched,
    silk,
    form6,
    recent,
    age,
    rating,
    rtgDelta,
    hw,
    bodyWt,
    gear,
    career,
    rail,
    dam,
    sire,
    damsire,
    owner,
    prize,
    finish,
    position,
    rank,
    placePos,
  ]);
}

/// Renders a Web odds number. Whole values drop the decimal; null is an em dash.
String formatOdds(double? value) {
  if (value == null) return '—';
  if (value == value.roundToDouble()) return value.toInt().toString();
  var text = value.toStringAsFixed(2);
  text = text.replaceFirst(RegExp(r'0+$'), '');
  text = text.replaceFirst(RegExp(r'\.$'), '');
  return text;
}

String _reqString(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value is String) return value;
  throw FormatException('欄位 $key 無法解析');
}

String? _optString(Map<String, dynamic> json, String key) {
  if (!json.containsKey(key) || json[key] == null) return null;
  final value = json[key];
  if (value is String) return value;
  throw FormatException('欄位 $key 無法解析');
}

int _reqInt(Map<String, dynamic> json, String key) {
  final value = _optInt(json, key);
  if (value == null) throw FormatException('欄位 $key 無法解析');
  return value;
}

int? _optInt(Map<String, dynamic> json, String key) {
  if (!json.containsKey(key) || json[key] == null) return null;
  final value = json[key];
  if (value is int) return value;
  if (value is double && value == value.roundToDouble()) return value.toInt();
  throw FormatException('欄位 $key 無法解析');
}

double? _optOdds(Map<String, dynamic> json, String key) {
  if (!json.containsKey(key) || json[key] == null) return null;
  final value = json[key];
  if (value is num) return value.toDouble();
  throw FormatException('欄位 $key 無法解析');
}

bool? _optBool(Map<String, dynamic> json, String key) {
  if (!json.containsKey(key) || json[key] == null) return null;
  final value = json[key];
  if (value is bool) return value;
  throw FormatException('欄位 $key 無法解析');
}

List<RaceDividend>? _optDividends(Map<String, dynamic> json) {
  if (!json.containsKey('dividends') || json['dividends'] == null) return null;
  final raw = json['dividends'];
  if (raw is! List) {
    throw FormatException('欄位 dividends 無法解析');
  }
  return [
    for (final item in raw)
      RaceDividend.fromJson(Map<String, dynamic>.from(item as Map)),
  ];
}
