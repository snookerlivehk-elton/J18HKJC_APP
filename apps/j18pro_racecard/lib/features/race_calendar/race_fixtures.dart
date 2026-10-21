import 'dart:convert';

import 'package:j18pro_racecard/domain/meeting.dart';

/// Web `raceCalScope`. Hong Kong is the default.
enum RaceCalendarScope { hk, os }

/// One Web `RACE_FIXTURES` / `OVERSEAS_FIXTURES` row.
class RaceFixture {
  const RaceFixture({
    required this.date,
    this.course,
    this.session,
    this.time,
    this.track,
    this.klass,
    this.going,
    this.dist,
    this.region,
    this.venue,
    this.venueLabel,
  });

  final String date;
  final String? course;
  final String? session;
  final String? time;
  final String? track;
  final String? klass;
  final String? going;
  final String? dist;
  final String? region;
  final String? venue;
  final String? venueLabel;

  factory RaceFixture.fromJson(Map<String, dynamic> json) {
    return RaceFixture(
      date: json['date'] as String,
      course: json['course'] as String?,
      session: json['session'] as String?,
      time: json['time'] as String?,
      track: json['track'] as String?,
      klass: json['klass'] as String?,
      going: json['going'] as String?,
      dist: json['dist']?.toString(),
      region: json['region'] as String?,
      venue: json['venue'] as String?,
      venueLabel: json['venueLabel'] as String?,
    );
  }
}

const _weekdayShort = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

const _hkFixtureJson =
    '[{"date":"2026-09-23","course":"HV","session":"night","time":"18:40","track":"草地","klass":"五班","going":"好地","dist":"1650"},'
    '{"date":"2026-10-01","course":"ST","session":"day","time":"13:00","track":"草地","klass":"四班","going":"好地","dist":"1400"},'
    '{"date":"2026-10-04","course":"ST","session":"day","time":"12:30","track":"全天候","klass":"五班","going":"封地","dist":"1650"},'
    '{"date":"2026-10-07","course":"HV","session":"night","time":"19:15","track":"草地","klass":"四班","going":"好地","dist":"1200"},'
    '{"date":"2026-10-11","course":"ST","session":"day","time":"13:00","track":"草地","klass":"三班","going":"好地","dist":"1600"},'
    '{"date":"2026-10-14","course":"HV","session":"night","time":"19:15","track":"草地","klass":"五班","going":"好地","dist":"1650"},'
    '{"date":"2026-10-19","course":"ST","session":"day","time":"13:15","track":"草地","klass":"四班","going":"好地","dist":"1200"},'
    '{"date":"2026-10-21","course":"HV","session":"night","time":"19:15","track":"草地","klass":"四班","going":"好地","dist":"1800"},'
    '{"date":"2026-10-25","course":"ST","session":"day","time":"12:45","track":"草地","klass":"三班","going":"好地","dist":"1400"},'
    '{"date":"2026-10-28","course":"ST","session":"night","time":"19:15","track":"全天候","klass":"四班","going":"封地","dist":"1200"},'
    '{"date":"2026-11-01","course":"HV","session":"day","time":"13:00","track":"草地","klass":"五班","going":"好地","dist":"1000"},'
    '{"date":"2026-11-04","course":"HV","session":"night","time":"19:15","track":"草地","klass":"四班","going":"好地","dist":"1650"},'
    '{"date":"2026-11-08","course":"ST","session":"day","time":"13:00","track":"草地","klass":"三班","going":"好地","dist":"1600"},'
    '{"date":"2026-11-11","course":"HV","session":"night","time":"19:15","track":"草地","klass":"五班","going":"好地","dist":"1200"},'
    '{"date":"2026-11-14","course":"ST","session":"day","time":"12:30","track":"全天候","klass":"四班","going":"封地","dist":"1650"},'
    '{"date":"2026-11-18","course":"HV","session":"night","time":"19:15","track":"草地","klass":"四班","going":"好地","dist":"1650"},'
    '{"date":"2026-11-22","course":"ST","session":"day","time":"13:00","track":"草地","klass":"三班","going":"好地","dist":"1400"},'
    '{"date":"2026-11-25","course":"HV","session":"night","time":"19:15","track":"草地","klass":"五班","going":"好地","dist":"1200"},'
    '{"date":"2026-11-29","course":"ST","session":"day","time":"13:15","track":"草地","klass":"四班","going":"好地","dist":"1800"},'
    '{"date":"2026-12-02","course":"HV","session":"night","time":"19:15","track":"草地","klass":"四班","going":"好地","dist":"1650"},'
    '{"date":"2026-12-06","course":"ST","session":"day","time":"13:00","track":"草地","klass":"三班","going":"好地","dist":"1600"},'
    '{"date":"2026-12-09","course":"HV","session":"night","time":"19:15","track":"草地","klass":"五班","going":"好地","dist":"1200"},'
    '{"date":"2026-12-13","course":"ST","session":"day","time":"12:45","track":"全天候","klass":"四班","going":"封地","dist":"1200"},'
    '{"date":"2026-12-16","course":"HV","session":"night","time":"19:15","track":"草地","klass":"四班","going":"好地","dist":"1650"},'
    '{"date":"2026-12-20","course":"ST","session":"day","time":"13:00","track":"草地","klass":"三班","going":"好地","dist":"1400"},'
    '{"date":"2026-12-23","course":"HV","session":"night","time":"19:15","track":"草地","klass":"五班","going":"好地","dist":"1800"},'
    '{"date":"2026-12-26","course":"ST","session":"day","time":"13:00","track":"草地","klass":"四班","going":"好地","dist":"1600"}]';

const _osFixtureJson =
    '[{"date":"2026-09-27","region":"UK","venue":"ASC","venueLabel":"雅士谷","time":"19:10","track":"草地","klass":"Listed","going":"好地","dist":"1600"},'
    '{"date":"2026-10-03","region":"AU","venue":"RAN","venueLabel":"蘭域","time":"12:30","track":"草地","klass":"G1","going":"好地","dist":"1400"},'
    '{"date":"2026-10-05","region":"UK","venue":"NBY","venueLabel":"紐百利","time":"20:05","track":"草地","klass":"Handicap","going":"好地","dist":"1200"},'
    '{"date":"2026-10-11","region":"FR","venue":"LON","venueLabel":"隆尚","time":"19:45","track":"草地","klass":"G2","going":"好地","dist":"1600"},'
    '{"date":"2026-10-18","region":"AU","venue":"CAU","venueLabel":"哥爾菲","time":"13:15","track":"草地","klass":"G1","going":"好地","dist":"2000"},'
    '{"date":"2026-10-25","region":"UK","venue":"ASC","venueLabel":"雅士谷","time":"21:00","track":"草地","klass":"G1","going":"好地","dist":"2400"},'
    '{"date":"2026-11-01","region":"AE","venue":"MEY","venueLabel":"美丹","time":"19:30","track":"泥地","klass":"G2","going":"快地","dist":"1600"},'
    '{"date":"2026-11-08","region":"AU","venue":"FLEM","venueLabel":"費明頓","time":"12:45","track":"草地","klass":"G1","going":"好地","dist":"3200"},'
    '{"date":"2026-11-15","region":"FR","venue":"CHA","venueLabel":"尚蒂伊","time":"20:20","track":"草地","klass":"G1","going":"好地","dist":"2100"},'
    '{"date":"2026-11-22","region":"UK","venue":"HAY","venueLabel":"希斯園","time":"19:55","track":"草地","klass":"G3","going":"好地","dist":"1400"},'
    '{"date":"2026-11-29","region":"AU","venue":"RAN","venueLabel":"蘭域","time":"13:00","track":"草地","klass":"G1","going":"好地","dist":"1600"},'
    '{"date":"2026-12-06","region":"AE","venue":"MEY","venueLabel":"美丹","time":"20:10","track":"泥地","klass":"G1","going":"快地","dist":"1900"},'
    '{"date":"2026-12-13","region":"UK","venue":"KEL","venueLabel":"京士頓","time":"19:40","track":"全天候","klass":"Handicap","going":"標準","dist":"1400"},'
    '{"date":"2026-12-20","region":"FR","venue":"DEA","venueLabel":"多維爾","time":"18:50","track":"草地","klass":"Listed","going":"好地","dist":"1500"}]';

List<RaceFixture>? _hk;
List<RaceFixture>? _os;

List<RaceFixture> fixturesFor(RaceCalendarScope scope) {
  if (scope == RaceCalendarScope.os) {
    return _os ??= _parse(_osFixtureJson);
  }
  return _hk ??= _parse(_hkFixtureJson);
}

List<RaceFixture> _parse(String raw) {
  final decoded = jsonDecode(raw) as List<dynamic>;
  return [
    for (final item in decoded)
      RaceFixture.fromJson(Map<String, dynamic>.from(item as Map)),
  ];
}

RaceFixture? fixtureOn(String iso, RaceCalendarScope scope) {
  for (final fixture in fixturesFor(scope)) {
    if (fixture.date == iso) return fixture;
  }
  return null;
}

/// Web `nearestFixtureDate`: latest fixture on or before [fromIso], else the first.
String? nearestFixtureDate(String? fromIso, RaceCalendarScope scope) {
  final dates = <String>[];
  final seen = <String>{};
  for (final fixture in fixturesFor(scope)) {
    if (seen.add(fixture.date)) dates.add(fixture.date);
  }
  dates.sort();
  if (dates.isEmpty) return fromIso;
  final today = (fromIso == null || fromIso.isEmpty) ? dates.first : fromIso;
  var best = dates.first;
  for (final date in dates) {
    if (date.compareTo(today) <= 0) {
      best = date;
    } else {
      break;
    }
  }
  return best;
}

String courseLabelOf(String? course) {
  if (course == 'ST') return '沙田';
  if (course == 'HV') return '跑馬地';
  return course ?? '';
}

String weekdayShort(DateTime date) => _weekdayShort[date.weekday % 7];

/// Web `formatMenuDate`: `2026/9/23 周三`.
String formatMenuDate(String? iso) {
  final parts = (iso ?? '').split('-');
  if (parts.length != 3) return '—';
  final y = int.tryParse(parts[0]);
  final m = int.tryParse(parts[1]);
  final d = int.tryParse(parts[2]);
  if (y == null || m == null || d == null || y == 0 || m == 0 || d == 0) {
    return '—';
  }
  final weekday = weekdayShort(DateTime(y, m, d));
  return '$y/$m/$d $weekday';
}

String defaultFixtureTime(RaceFixture? fixture) {
  if (fixture?.time != null && fixture!.time!.isNotEmpty) return fixture.time!;
  if (fixture == null) return '—';
  if (fixture.region != null) return '19:30';
  return fixture.session == 'night' ? '19:15' : '13:00';
}

/// Web `formatFixtureMetaLine`.
String formatFixtureMetaLine(RaceFixture? fixture) {
  if (fixture == null || fixture.date.isEmpty) return '該日暫無賽事';
  final parts = fixture.date.split('-');
  var md = '';
  var weekday = '';
  if (parts.length == 3) {
    final y = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    final d = int.tryParse(parts[2]);
    if (y != null && m != null && d != null) {
      md = '$d/$m';
      weekday = weekdayShort(DateTime(y, m, d));
    }
  }
  final time = defaultFixtureTime(fixture);
  if (fixture.region != null || fixture.venueLabel != null) {
    return [
      md,
      weekday,
      time,
      fixture.venueLabel ?? fixture.venue ?? '外地',
      fixture.track ?? '草地',
      fixture.klass ?? '—',
      (fixture.dist ?? '').replaceAll('米', ''),
      fixture.going ?? '—',
    ].where((part) => part.trim().isNotEmpty).join(' ');
  }
  final trackRaw =
      fixture.track ??
      (fixture.course == 'ST' && fixture.session == 'night' ? '全天候' : '草地');
  var surface = trackRaw;
  if (trackRaw == '草地') {
    surface = fixture.course == 'HV' ? '谷草' : '田草';
  }
  final going = fixture.going ?? (trackRaw == '全天候' ? '封地' : '好地');
  return [
    md,
    weekday,
    time,
    surface,
    fixture.klass ?? '',
    (fixture.dist ?? '').replaceAll('米', ''),
    going,
  ].where((part) => part.trim().isNotEmpty).join(' ');
}

/// Web `fixtureMarkClass`.
String fixtureMarkClass(RaceFixture fixture) {
  final region = fixture.region?.toUpperCase();
  if (region != null) {
    return switch (region) {
      'UK' => 'os-uk',
      'AU' => 'os-au',
      'FR' => 'os-fr',
      'AE' => 'os-ae',
      _ => 'os-uk',
    };
  }
  if (fixture.course == 'ST' && fixture.session == 'night') return 'st-night';
  if (fixture.course == 'HV' && fixture.session == 'day') return 'hv-day';
  if (fixture.course == 'HV') return 'hv-night';
  return 'st-day';
}

/// Web `buildStubMeeting`. The snapshot date is loaded separately.
Meeting buildStubMeeting(
  String iso, {
  RaceCalendarScope scope = RaceCalendarScope.hk,
}) {
  final parts = iso.split('-');
  final y = parts.length == 3 ? int.tryParse(parts[0]) : null;
  final m = parts.length == 3 ? int.tryParse(parts[1]) : null;
  final d = parts.length == 3 ? int.tryParse(parts[2]) : null;
  final weekday = (y != null && m != null && d != null)
      ? weekdayShort(DateTime(y, m, d))
      : '';
  final fixture = fixtureOn(iso, scope);
  final overseas = scope == RaceCalendarScope.os;
  final course = overseas
      ? (fixture?.venueLabel ?? fixture?.venue ?? '外地')
      : courseLabelOf(fixture?.course);
  final name = overseas ? (fixture?.venueLabel ?? '外地賽事') : '賽事資料載入中';
  return Meeting(
    date: iso,
    y: parts.isNotEmpty ? parts[0] : '',
    m: parts.length > 1 ? parts[1] : '',
    d: parts.length > 2 ? parts[2] : '',
    weekday: weekday,
    courseLabel: course,
    source: overseas
        ? 'HKJC overseas fixture stub（日後接外馬排位 API）'
        : 'HKJC local fixture stub（日後接排位 API）',
    races: [
      Race(
        num: 1,
        name: name,
        time: defaultFixtureTime(fixture ?? RaceFixture(date: iso)),
        meta: formatFixtureMetaLine(fixture ?? RaceFixture(date: iso)),
        runners: const [],
      ),
    ],
  );
}
