import 'dart:math' as math;

import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/index_picks.dart';

const waterHourCount = 8;

/// One hour of Web `waterHourSample` (win / place / WP, water then flow).
class WaterSample {
  const WaterSample({
    this.winW,
    this.winF,
    this.plaW,
    this.plaF,
    this.wpW,
    this.wpF,
  });

  final int? winW;
  final int? winF;
  final int? plaW;
  final int? plaF;
  final int? wpW;
  final int? wpF;

  bool get isEmpty =>
      winW == null &&
      winF == null &&
      plaW == null &&
      plaF == null &&
      wpW == null &&
      wpF == null;
}

int? placeWaterOf(Runner runner, int raceNum) {
  if (runner.scratched) return null;
  int? value;
  if (runner.place != null) {
    final base = winWaterOf(runner, raceNum) ?? 70;
    value = math.max(35, math.min(99, base - 2 - (runner.no % 4)));
  }
  if (raceNum == 1 && runner.no == 9) return 84;
  return value;
}

int? placeFlowOf(Runner runner, int raceNum) {
  if (runner.scratched) return null;
  int? value;
  if (runner.place != null) {
    final winFlow = winFlowOf(runner, raceNum) ?? 8;
    value = math.max(
      1,
      math.min(25, jsRound(winFlow * 0.55) + (runner.no % 3)),
    );
  }
  if (raceNum == 1 && runner.no == 9) return 5;
  return value;
}

int? wpWaterOf(Runner runner, int raceNum) {
  if (runner.scratched) return null;
  final value = math.max(
    30,
    math.min(99, 70 + ((runner.no * 5 + raceNum * 3) % 13) - 6),
  );
  if (raceNum == 1 && runner.no == 9) return 80;
  return value;
}

int? wpFlowOf(Runner runner, int raceNum) {
  if (runner.scratched) return null;
  final value = math.max(0, math.min(40, 6 + ((runner.no * 4 + raceNum) % 8)));
  if (raceNum == 1 && runner.no == 9) return 6;
  return value;
}

int _clampInt(num value, int lo, int hi) {
  final rounded = jsRound(value);
  if (rounded < lo) return lo;
  if (rounded > hi) return hi;
  return rounded;
}

/// Web `waterHourSample`. [hourAgo] 0 is the latest hour.
WaterSample waterHourSample(Runner runner, int raceNum, int hourAgo) {
  if (runner.scratched) return const WaterSample();
  final hourIdx = math.max(0, hourAgo);
  final jitter = ((runner.no * 3 + raceNum * 5 + hourIdx * 7) % 5) - 2;
  final winW0 = winWaterOf(runner, raceNum);
  final plaW0 = placeWaterOf(runner, raceNum);
  final wpW0 = wpWaterOf(runner, raceNum);
  final winF0 = winFlowOf(runner, raceNum);
  final plaF0 = placeFlowOf(runner, raceNum);
  final wpF0 = wpFlowOf(runner, raceNum);
  return WaterSample(
    winW: winW0 == null
        ? null
        : _clampInt(winW0 + hourIdx * 1.2 + jitter, 40, 99),
    plaW: plaW0 == null
        ? null
        : _clampInt(plaW0 + hourIdx * 1.0 + (jitter % 3), 35, 99),
    wpW: wpW0 == null
        ? null
        : _clampInt(wpW0 + hourIdx * 1.1 + ((jitter + 1) % 3), 30, 99),
    winF: winF0 == null
        ? null
        : _clampInt(winF0 - hourIdx + ((runner.no + hourIdx) % 3), 0, 40),
    plaF: plaF0 == null
        ? null
        : _clampInt(
            plaF0 - math.max(0, hourIdx - 1) + ((runner.no * 2 + hourIdx) % 3),
            0,
            40,
          ),
    wpF: wpF0 == null
        ? null
        : _clampInt(
            wpF0 - math.max(0, hourIdx - 1) + ((runner.no + hourIdx * 2) % 3),
            0,
            40,
          ),
  );
}

/// Web `waterTrendDir`: current versus the earlier hour on the right.
String waterTrendDir(int? current, int? earlier) {
  if (current == null || earlier == null || current == earlier) return '';
  return current > earlier ? 'up' : 'down';
}

/// Web `parseMeetHour` on the race time, else the meta line.
int parseMeetHour(Race race) {
  final source = race.time.isNotEmpty ? race.time : race.meta;
  final match = RegExp(r'(\d{1,2})\s*:\s*(\d{2})').firstMatch(source);
  if (match == null) return 14;
  final hour = int.parse(match.group(1)!);
  if (hour < 0) return 0;
  if (hour > 23) return 23;
  return hour;
}

List<String> waterHourLabels(int baseHour, {int count = waterHourCount}) {
  return [
    for (var i = 0; i < count; i++)
      '${((baseHour - i + 24) % 24).toString().padLeft(2, '0')}:00',
  ];
}

String formatWater(int? value) => value == null ? '—' : '$value';

String formatFlow(int? value) {
  if (value == null) return '—';
  return value.toString().padLeft(2, '0');
}
