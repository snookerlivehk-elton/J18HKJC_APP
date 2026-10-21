import 'dart:math' as math;

import 'package:j18pro_racecard/domain/meeting.dart';

/// Web qin matrix.
///
/// Odds are synthesized from 獨贏 (正Q) or 位置 (位置Q). api_jjjc has no QIN
/// or QPL export, so this stays a demo seam until a real board exists.
enum QinMode { qin, qpl }

enum QinDrop { none, drop20, drop50 }

/// At most this many runners. Web `QIN_MAX_N`.
const qinMaxRunners = 20;

/// Web `QIN_FIT_N`. Wider fields scroll instead of shrinking past this.
const qinFitRunners = 14;

class QinPair {
  const QinPair({
    required this.a,
    required this.b,
    required this.odds,
    required this.index,
    required this.scratched,
    required this.hot,
    required this.drop,
  });

  final int a;
  final int b;
  final double? odds;
  final int? index;
  final bool scratched;
  final bool hot;
  final QinDrop drop;

  String get storageKey => a < b ? '$a-$b' : '$b-$a';
}

class QinBoard {
  const QinBoard({
    required this.nos,
    required this.scratch,
    required this.mode,
    required this.hotKey,
    required this.pairs,
  });

  final List<int> nos;
  final Map<int, bool> scratch;
  final QinMode mode;
  final String? hotKey;
  final Map<String, QinPair> pairs;

  bool scratchedNo(int no) => scratch[no] ?? false;

  QinPair? pair(int a, int b) => pairs[a < b ? '$a-$b' : '$b-$a'];
}

String qinPairKey(int a, int b) => a < b ? '$a-$b' : '$b-$a';

/// Web `synthQinOdds` / `synthQplOdds`.
double? synthComboOdds(double? left, double? right, double factor) {
  if (left == null || right == null) return null;
  final value = left * right * factor;
  if (value >= 999) return 999;
  if (value >= 100) return value.roundToDouble();
  if (value >= 20) return (value * 2).round() / 2;
  return (value * 10).round() / 10;
}

/// Web `fmtQinOdds`.
String fmtQinOdds(double? value) {
  if (value == null) return '—';
  if (value >= 100) return value.round().toString();
  if (value == value.roundToDouble()) return value.toInt().toString();
  return value.toStringAsFixed(1);
}

/// Web `synthQinIndex`.
int? synthQinIndex(double? odds) {
  if (odds == null) return null;
  final raw = 98 - math.log(math.max(odds, 1.05)) / math.ln10 * 14;
  return math.max(70, math.min(92, raw.round()));
}

/// Web `qinDropClass`. Hot cells skip this.
QinDrop qinDrop({
  required int a,
  required int b,
  required int raceNum,
  required QinMode mode,
}) {
  final seed = mode == QinMode.qpl ? 7 : 0;
  final slot = (a * 17 + b * 31 + (raceNum + seed) * 13) % 23;
  if (slot == 0) return QinDrop.drop50;
  if (slot == 1 || slot == 2) return QinDrop.drop20;
  return QinDrop.none;
}

QinBoard buildQinBoard(Race race, QinMode mode) {
  final runners = [...race.runners]..sort((a, b) => a.no.compareTo(b.no));
  final kept = runners.length > qinMaxRunners
      ? runners.sublist(0, qinMaxRunners)
      : runners;
  final scratch = <int, bool>{
    for (final runner in kept) runner.no: runner.scratched,
  };
  final byNo = <int, Runner>{for (final runner in kept) runner.no: runner};
  final nos = [for (final runner in kept) runner.no];
  final usePlace = mode == QinMode.qpl;
  final pairs = <String, QinPair>{};
  String? hotKey;
  var hotOdds = double.infinity;
  for (var i = 0; i < nos.length; i++) {
    for (var j = i + 1; j < nos.length; j++) {
      final a = nos[i];
      final b = nos[j];
      final key = qinPairKey(a, b);
      final scratched = scratch[a]! || scratch[b]!;
      final odds = scratched
          ? null
          : synthComboOdds(
              usePlace ? byNo[a]!.place : byNo[a]!.win,
              usePlace ? byNo[b]!.place : byNo[b]!.win,
              usePlace ? 0.62 : 0.26,
            );
      if (odds != null && odds < hotOdds) {
        hotOdds = odds;
        hotKey = key;
      }
      pairs[key] = QinPair(
        a: a,
        b: b,
        odds: odds,
        index: scratched ? null : synthQinIndex(odds),
        scratched: scratched,
        hot: false,
        drop: QinDrop.none,
      );
    }
  }
  if (hotKey != null) {
    final hot = pairs[hotKey]!;
    pairs[hotKey] = QinPair(
      a: hot.a,
      b: hot.b,
      odds: hot.odds,
      index: hot.index,
      scratched: false,
      hot: true,
      drop: QinDrop.none,
    );
  }
  for (final entry in pairs.entries.toList()) {
    final pair = entry.value;
    if (pair.hot || pair.scratched) continue;
    pairs[entry.key] = QinPair(
      a: pair.a,
      b: pair.b,
      odds: pair.odds,
      index: pair.index,
      scratched: false,
      hot: false,
      drop: qinDrop(a: pair.a, b: pair.b, raceNum: race.num, mode: mode),
    );
  }
  return QinBoard(
    nos: nos,
    scratch: scratch,
    mode: mode,
    hotKey: hotKey,
    pairs: pairs,
  );
}
