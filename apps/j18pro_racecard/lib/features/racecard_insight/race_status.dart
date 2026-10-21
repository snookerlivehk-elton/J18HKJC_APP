import 'package:flutter/material.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/payout_detail.dart';

/// Web `RACE_STATUS` keys.
enum RaceStatusKind { wait, parade, gate, running, paid }

/// Web label for [kind].
String raceStatusLabel(RaceStatusKind kind) {
  return switch (kind) {
    RaceStatusKind.wait => '待開賽',
    RaceStatusKind.parade => '出跑道',
    RaceStatusKind.gate => '入閘中',
    RaceStatusKind.running => '開跑中',
    RaceStatusKind.paid => '已派彩',
  };
}

/// Text and dot colors. Light text uses the dedicated hexes; dots follow the
/// CSS variables. Dark text and dots both follow the dark CSS variables.
class RaceStatusColors {
  const RaceStatusColors({required this.text, required this.dot});

  final Color text;
  final Color dot;
}

RaceStatusColors raceStatusColors(RaceStatusKind kind, Brightness brightness) {
  if (brightness == Brightness.dark) {
    return switch (kind) {
      RaceStatusKind.wait => const RaceStatusColors(
        text: Color(0xFF6EB3E0),
        dot: Color(0xFF6EB3E0),
      ),
      RaceStatusKind.parade => const RaceStatusColors(
        text: Color(0xFF5CB86A),
        dot: Color(0xFF5CB86A),
      ),
      RaceStatusKind.gate => const RaceStatusColors(
        text: Color(0xFFE0C35A),
        dot: Color(0xFFE0C35A),
      ),
      RaceStatusKind.running => const RaceStatusColors(
        text: Color(0xFFFF7A6E),
        dot: Color(0xFFFF7A6E),
      ),
      RaceStatusKind.paid => const RaceStatusColors(
        text: Color(0xFFE39A45),
        dot: Color(0xFFE39A45),
      ),
    };
  }
  return switch (kind) {
    RaceStatusKind.wait => const RaceStatusColors(
      text: Color(0xFF3B8FD4),
      dot: Color(0xFF5BA3D9),
    ),
    RaceStatusKind.parade => const RaceStatusColors(
      text: Color(0xFF3D9A3D),
      dot: Color(0xFF5CB85C),
    ),
    RaceStatusKind.gate => const RaceStatusColors(
      text: Color(0xFFA67F0F),
      dot: Color(0xFFD4A017),
    ),
    RaceStatusKind.running => const RaceStatusColors(
      text: Color(0xFFC0392B),
      dot: Color(0xFFE74C3C),
    ),
    RaceStatusKind.paid => const RaceStatusColors(
      text: Color(0xFFC46E18),
      dot: Color(0xFFE88B2A),
    ),
  };
}

const _weekdayShort = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

final _timePattern = RegExp(r'(\d{1,2})\s*:\s*(\d{2})');
final _surfacePattern = RegExp(r'(谷草|田草|全天候|泥地|草地)');
final _classPattern = RegExp(r'(第?[一二三四五]班|[1-5]班)');
final _distPattern = RegExp(r'(\d{3,4})\s*米');
final _railPattern = RegExp('["“”]([A-Za-z+\\-]+)["“”]');
final _goingPattern = RegExp(r'(好地至快地|好地|快地|濕慢地|封地|標準)');

const _classMap = {
  '第一班': '一班',
  '第二班': '二班',
  '第三班': '三班',
  '第四班': '四班',
  '第五班': '五班',
};

/// Local start, matching `new Date(y, m - 1, d, hh, mm)`.
DateTime? parseRaceStart(String? dateIso, String? timeStr) {
  final parts = (dateIso ?? '').split('-');
  if (parts.length != 3) return null;
  final y = int.tryParse(parts[0]);
  final m = int.tryParse(parts[1]);
  final d = int.tryParse(parts[2]);
  if (y == null || m == null || d == null || y == 0 || m == 0 || d == 0) {
    return null;
  }
  final match = _timePattern.firstMatch(timeStr ?? '');
  final hh = match == null ? 13 : int.parse(match.group(1)!);
  final mm = match == null ? 0 : int.parse(match.group(2)!);
  return DateTime(y, m, d, hh, mm);
}

/// Minutes from [now] until the race. Null when the date cannot be parsed.
double? minutesUntilRaceStart(String? dateIso, String? timeStr, DateTime now) {
  final start = parseRaceStart(dateIso, timeStr);
  if (start == null) return null;
  return start.difference(now).inMilliseconds / 60000;
}

/// Web `resolveRaceStatus`. [minutesUntil] wins when provided (tests).
RaceStatusKind resolveRaceStatus({
  required Race race,
  required String dateIso,
  DateTime? now,
  double? minutesUntil,
}) {
  if (raceHasPayout(race)) return RaceStatusKind.paid;
  final mins =
      minutesUntil ??
      minutesUntilRaceStart(
        dateIso,
        race.time.isNotEmpty ? race.time : race.meta,
        now ?? DateTime.now(),
      );
  if (mins == null || mins.isNaN || mins.isInfinite) return RaceStatusKind.wait;
  if (mins < 0) return RaceStatusKind.running;
  if (mins > 30) return RaceStatusKind.wait;
  if (mins > 15) return RaceStatusKind.parade;
  if (mins > 5) return RaceStatusKind.gate;
  return RaceStatusKind.running;
}

/// Web `formatRaceInfoLine`. Long lines are ellipsized by the status row.
String formatRaceInfoLine({
  required String? dateIso,
  required Race? race,
  String? courseLabel,
  String? weekdayLabel,
}) {
  if (race == null) return '該日暫無賽事';
  final parts = (dateIso ?? '').split('-');
  String md = '';
  String weekday = '';
  if (parts.length == 3) {
    final y = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    final d = int.tryParse(parts[2]);
    if (y != null && m != null && d != null && m != 0 && d != 0) {
      md = '$d/$m';
      weekday = _weekdayShort[DateTime(y, m, d).weekday % 7];
    }
  } else if (weekdayLabel != null && weekdayLabel.isNotEmpty) {
    weekday = weekdayLabel.replaceFirst(RegExp(r'^星期'), '周');
  }
  final raw = race.meta;
  final time = race.time.isNotEmpty
      ? race.time
      : (_timePattern.firstMatch(raw)?.group(0) ?? '—');
  var surface = '';
  final surfaceMatch = _surfacePattern.firstMatch(raw);
  if (surfaceMatch != null) {
    final token = surfaceMatch.group(1)!;
    if (token == '草地') {
      surface = courseLabel == '跑馬地' ? '谷草' : '田草';
    } else {
      surface = token;
    }
  } else if (courseLabel == '跑馬地') {
    surface = '谷草';
  } else if (courseLabel != null && courseLabel.isNotEmpty) {
    surface = '田草';
  }
  var klass = '';
  final classMatch = _classPattern.firstMatch(raw);
  if (classMatch != null) {
    final token = classMatch.group(1)!;
    klass = _classMap[token] ?? token.replaceFirst(RegExp(r'^第'), '');
  }
  var dist = '';
  final distMatch = _distPattern.firstMatch(raw);
  if (distMatch != null) dist = distMatch.group(1)!;
  var rail = '';
  final railMatch = _railPattern.firstMatch(raw);
  if (railMatch != null) {
    rail = ' "${railMatch.group(1)}"';
  }
  var going = '';
  final goingMatch = _goingPattern.firstMatch(raw);
  if (goingMatch != null) going = goingMatch.group(1)!;
  final fields = <String>[
    md,
    weekday,
    time,
    surface,
    klass,
    dist,
    rail,
    going,
    race.name,
  ];
  return fields.where((field) => field.trim().isNotEmpty).join(' ');
}
