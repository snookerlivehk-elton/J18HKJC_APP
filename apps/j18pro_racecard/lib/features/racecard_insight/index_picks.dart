import 'dart:math' as math;

import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/time_scrub.dart';

/// Web `INDEX_STRATEGIES` entry.
class IndexStrategy {
  const IndexStrategy({
    required this.id,
    required this.label,
    required this.lines,
  });

  final String id;
  final String label;
  final List<String> lines;
}

const indexStrategies = <IndexStrategy>[
  IndexStrategy(id: 'composite', label: '綜合指數', lines: ['綜合', '指數']),
  IndexStrategy(id: 'energy', label: '能量蓄勢', lines: ['能量', '蓄勢']),
  IndexStrategy(id: 'expert', label: '名家權重', lines: ['名家', '權重']),
  IndexStrategy(id: 'water', label: '水位排名', lines: ['水位', '排名']),
  IndexStrategy(id: 'flow', label: '流量排名', lines: ['流量', '排名']),
];

const defaultIndexPickLimit = 6;

IndexStrategy indexStrategyById(String? id) {
  for (final strategy in indexStrategies) {
    if (strategy.id == id) return strategy;
  }
  return indexStrategies.first;
}

String canonicalIndexStrategyId(String? id) => indexStrategyById(id).id;

/// `Math.round` for finite values: half rounds toward positive infinity.
int jsRound(num value) {
  if (value.isNaN || value.isInfinite) {
    throw ArgumentError.value(value, 'value', 'not finite');
  }
  return (value + 0.5).floor();
}

/// Web `parseSignedNum`.
double? parseSignedNum(String? value) {
  if (value == null) return null;
  var text = value.trim();
  if (text.isEmpty) return null;
  if (text.startsWith('+')) text = text.substring(1);
  return double.tryParse(text);
}

/// Web `ensureWaterFlowDemo` win-water, including the race 1 horse 9 anchor.
int? winWaterOf(Runner runner, int raceNum) {
  if (runner.scratched) return null;
  int? value;
  final win = runner.win;
  if (win != null) {
    final raw = 100 - math.min(win, 40) * 1.6 + ((runner.no * 3 + raceNum) % 7);
    value = math.max(40, math.min(99, jsRound(raw)));
  }
  if (raceNum == 1 && runner.no == 9) return 86;
  return value;
}

/// Web `ensureWaterFlowDemo` win-flow, including the race 1 horse 9 anchor.
int? winFlowOf(Runner runner, int raceNum) {
  if (runner.scratched) return null;
  int? value;
  final win = runner.win;
  if (win != null) {
    final raw = 28 / math.max(win, 1.2) + ((runner.no + raceNum) % 5);
    value = math.max(1, math.min(30, jsRound(raw)));
  }
  if (raceNum == 1 && runner.no == 9) return 10;
  return value;
}

int? finishOfRunner(Runner runner) {
  if (runner.scratched) return null;
  return runner.finish ?? runner.position ?? runner.rank ?? runner.placePos;
}

/// Web `indexPicksForStrategy`. Scratched runners are left out.
List<int> indexPicksForStrategy(
  Race race,
  String? strategyId, {
  int limit = defaultIndexPickLimit,
}) {
  final id = canonicalIndexStrategyId(strategyId);
  final rows = [
    for (final runner in race.runners)
      if (!runner.scratched) runner,
  ];
  int cmpNum(
    Runner a,
    Runner b,
    num? Function(Runner runner) read, {
    required bool desc,
  }) {
    final av = read(a);
    final bv = read(b);
    if (av == null && bv == null) return a.no.compareTo(b.no);
    if (av == null) return 1;
    if (bv == null) return -1;
    if (av != bv) {
      final order = av.compareTo(bv);
      return desc ? -order : order;
    }
    return a.no.compareTo(b.no);
  }

  if (id == 'water') {
    rows.sort(
      (a, b) =>
          cmpNum(a, b, (runner) => winWaterOf(runner, race.num), desc: true),
    );
  } else if (id == 'flow') {
    rows.sort(
      (a, b) =>
          cmpNum(a, b, (runner) => winFlowOf(runner, race.num), desc: true),
    );
  } else if (id == 'expert') {
    rows.sort((a, b) => cmpNum(a, b, (runner) => runner.rating, desc: true));
  } else if (id == 'energy') {
    double score(Runner runner) {
      final win = runner.win;
      final usedWin = (win == null || win == 0) ? 99.0 : win;
      final hw = runner.hw;
      final usedHw = (hw == null || hw == 0) ? 120.0 : hw.toDouble();
      final delta = parseSignedNum(runner.rtgDelta);
      return usedHw / usedWin + (delta == null ? 0 : delta * 0.08);
    }

    rows.sort((a, b) {
      final diff = score(b).compareTo(score(a));
      if (diff != 0) return diff;
      return a.no.compareTo(b.no);
    });
  } else {
    rows.sort(
      (a, b) =>
          cmpNum(a, b, (runner) => winWaterOf(runner, race.num), desc: false),
    );
  }
  final count = math.min(limit, rows.length);
  return [for (var i = 0; i < count; i++) rows[i].no];
}

/// Picks shown in the index capsule: the active scrub point's rotation.
List<int> activeIndexPicks({
  required Race race,
  required String strategyId,
  required int scrubPointIdx,
  int limit = defaultIndexPickLimit,
}) {
  final base = indexPicksForStrategy(race, strategyId, limit: limit);
  final points = buildScrubPicks(base);
  if (points.isEmpty) return const [];
  return points[activeScrubIndex(scrubPointIdx, points.length)];
}

/// Web `payoutFinishNosForRace`.
List<int> payoutFinishNosForRace(Race race) {
  final runners = [
    for (final runner in race.runners)
      if (!runner.scratched) runner,
  ];
  if (runners.isEmpty) return const [];
  final hasFinish = runners.every((runner) => finishOfRunner(runner) != null);
  final sorted = [...runners]
    ..sort((a, b) {
      if (hasFinish) {
        final fa = finishOfRunner(a)!;
        final fb = finishOfRunner(b)!;
        if (fa != fb) return fa.compareTo(fb);
        return a.no.compareTo(b.no);
      }
      final aw = a.win;
      final bw = b.win;
      if (aw == null && bw == null) return a.no.compareTo(b.no);
      if (aw == null) return 1;
      if (bw == null) return -1;
      if (aw != bw) return aw.compareTo(bw);
      return a.no.compareTo(b.no);
    });
  return [for (final runner in sorted) runner.no];
}
