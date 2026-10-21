import 'dart:math' as math;

import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/index_picks.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/racecard_insight/payout_detail.dart';

/// Web `TIP_NOTE_MAX`. Demo fills each empty race with this many shortest prices.
const tipNoteMax = 6;

/// Web `TIP_RECORD_STAKE`. Estimated return is stake times a demo dividend.
const tipRecordStake = 10;

/// Web `TIP_SETTLED_TREAT_BEFORE_CURRENT_AS_PAID`.
///
/// Default off. Earlier races are settled only when the card itself is paid.
/// `--dart-define=J18_DEMO_TIP_SETTLE_BEFORE_CURRENT=true` turns the demo
/// colouring back on. This flag belongs to tip-record, not famous tips.
const tipSettledTreatBeforeCurrentAsPaid = bool.fromEnvironment(
  'J18_DEMO_TIP_SETTLE_BEFORE_CURRENT',
  defaultValue: false,
);

/// Web `TIP_STAT_DEFS`.
const tipStatDefs = <TipStatDef>[
  TipStatDef(key: 'win', name: '獨贏', range: '前2個號碼', help: '心水序號第1–2名中有冠軍即計中'),
  TipStatDef(key: 'qin', name: '連贏', range: '前3個號碼', help: '心水序號第1–3名同時包含冠、亞軍'),
  TipStatDef(
    key: 'top3',
    name: '前三',
    range: '前4個號碼',
    help: '心水序號第1–4名同時包含冠、亞、季軍',
  ),
  TipStatDef(key: 'fourth', name: '第四名', range: '全部號碼', help: '心水全部號碼中含第四名'),
  TipStatDef(
    key: 'tierce',
    name: '單T',
    range: '全部號碼',
    help: '心水全部號碼同時包含冠、亞、季軍',
  ),
  TipStatDef(
    key: 'qpl',
    name: '孖寶',
    range: '全部號碼',
    help: '心水全部號碼同時包含冠亞、冠季或亞季任一對',
  ),
  TipStatDef(key: 'quartet', name: '四連環', range: '全部號碼', help: '心水全部號碼同時包含前四名'),
];

/// Web help footer under the stat definitions.
const tipRecordHelpFooter = '投注基礎按每注 10 元估算累積獎金；準確率同時顯示勝場／參與場，避免單場中獎即 100%。';

/// Web `TIP_LEADERBOARD_DEMO`. Headline [TipLeader.prize] is not the sum of rows.
const tipLeaderboard = <TipLeader>[
  TipLeader(
    id: 'u1',
    name: '谷草快手',
    prize: 18640,
    stats: {
      'win': [18, 42, 5200],
      'qin': [12, 40, 3800],
      'top3': [16, 40, 3200],
      'fourth': [9, 38, 1400],
      'tierce': [7, 36, 2100],
      'qpl': [14, 40, 2200],
      'quartet': [4, 32, 740],
    },
  ),
  TipLeader(
    id: 'u2',
    name: '沙田夜鷹',
    prize: 15220,
    stats: {
      'win': [15, 48, 4300],
      'qin': [11, 46, 3100],
      'top3': [14, 46, 2700],
      'fourth': [8, 44, 1200],
      'tierce': [6, 40, 1700],
      'qpl': [12, 46, 1800],
      'quartet': [3, 30, 420],
    },
  ),
  TipLeader(
    id: 'u3',
    name: '欄位獵人',
    prize: 12880,
    stats: {
      'win': [14, 50, 3600],
      'qin': [10, 48, 2600],
      'top3': [13, 48, 2300],
      'fourth': [7, 45, 980],
      'tierce': [5, 38, 1400],
      'qpl': [11, 48, 1600],
      'quartet': [3, 28, 400],
    },
  ),
  TipLeader(
    id: 'u4',
    name: '初段節奏',
    prize: 10950,
    stats: {
      'win': [12, 44, 3100],
      'qin': [9, 42, 2200],
      'top3': [11, 42, 1900],
      'fourth': [6, 40, 820],
      'tierce': [4, 34, 1200],
      'qpl': [10, 42, 1400],
      'quartet': [2, 26, 330],
    },
  ),
  TipLeader(
    id: 'u5',
    name: '直路勁抽',
    prize: 9740,
    stats: {
      'win': [11, 46, 2800],
      'qin': [8, 44, 1900],
      'top3': [10, 44, 1700],
      'fourth': [6, 42, 760],
      'tierce': [4, 36, 1100],
      'qpl': [9, 44, 1200],
      'quartet': [2, 24, 280],
    },
  ),
  TipLeader(
    id: 'u6',
    name: '班次升級',
    prize: 8620,
    stats: {
      'win': [10, 40, 2500],
      'qin': [7, 38, 1700],
      'top3': [9, 38, 1500],
      'fourth': [5, 36, 680],
      'tierce': [3, 30, 900],
      'qpl': [8, 38, 1100],
      'quartet': [2, 22, 240],
    },
  ),
  TipLeader(
    id: 'u7',
    name: '泥地專家',
    prize: 7910,
    stats: {
      'win': [9, 42, 2300],
      'qin': [7, 40, 1600],
      'top3': [8, 40, 1400],
      'fourth': [5, 38, 640],
      'tierce': [3, 32, 820],
      'qpl': [7, 40, 980],
      'quartet': [1, 20, 170],
    },
  ),
  TipLeader(
    id: 'u8',
    name: '外檔奇兵',
    prize: 6840,
    stats: {
      'win': [8, 38, 2000],
      'qin': [6, 36, 1400],
      'top3': [7, 36, 1200],
      'fourth': [4, 34, 520],
      'tierce': [2, 28, 700],
      'qpl': [6, 36, 860],
      'quartet': [1, 18, 160],
    },
  ),
  TipLeader(
    id: 'u9',
    name: '短途閃電',
    prize: 6020,
    stats: {
      'win': [7, 36, 1800],
      'qin': [5, 34, 1200],
      'top3': [6, 34, 1050],
      'fourth': [4, 32, 480],
      'tierce': [2, 26, 620],
      'qpl': [5, 34, 740],
      'quartet': [1, 16, 130],
    },
  ),
  TipLeader(
    id: 'u10',
    name: '長途耐力',
    prize: 5410,
    stats: {
      'win': [6, 34, 1600],
      'qin': [5, 32, 1100],
      'top3': [6, 32, 980],
      'fourth': [3, 30, 400],
      'tierce': [2, 24, 560],
      'qpl': [5, 32, 660],
      'quartet': [1, 14, 110],
    },
  ),
];

class TipStatDef {
  const TipStatDef({
    required this.key,
    required this.name,
    required this.range,
    required this.help,
  });

  final String key;
  final String name;
  final String range;
  final String help;
}

class TipLeader {
  const TipLeader({
    required this.id,
    required this.name,
    required this.prize,
    required this.stats,
  });

  final String id;
  final String name;
  final int prize;

  /// `[wins, plays, prize]` per stat key.
  final Map<String, List<int>> stats;
}

class TipStatLine {
  const TipStatLine({
    required this.wins,
    required this.plays,
    required this.prize,
  });

  final int wins;
  final int plays;
  final int prize;
}

class TipRaceEval {
  const TipRaceEval({
    required this.picks,
    required this.settled,
    required this.hits,
    required this.prizes,
  });

  final List<int> picks;
  final bool settled;
  final Map<String, bool> hits;
  final Map<String, int> prizes;

  factory TipRaceEval.blank(List<int> picks) {
    return TipRaceEval(
      picks: picks,
      settled: false,
      hits: {for (final def in tipStatDefs) def.key: false},
      prizes: {for (final def in tipStatDefs) def.key: 0},
    );
  }
}

/// Web `tipStatTriple`.
({int wins, int plays, int prize}) tipStatTriple(List<int>? pair) {
  final wins = pair != null && pair.isNotEmpty ? pair[0] : 0;
  final plays = pair != null && pair.length > 1 ? pair[1] : 0;
  final prize = pair != null && pair.length > 2
      ? pair[2]
      : wins * 180 + plays * 4;
  return (wins: wins, plays: plays, prize: prize);
}

/// Web `tipMeetingDayLabel`. No leading zeros.
String tipMeetingDayLabel(Meeting meeting) {
  final day = meeting.d.trim();
  final month = meeting.m.trim();
  final dayNum = int.tryParse(day);
  final monthNum = int.tryParse(month);
  if (day.isNotEmpty &&
      month.isNotEmpty &&
      dayNum != null &&
      monthNum != null) {
    return '$dayNum/$monthNum';
  }
  final parts = meeting.date.split('-');
  if (parts.length == 3) {
    final parsedDay = int.tryParse(parts[2]);
    final parsedMonth = int.tryParse(parts[1]);
    if (parsedDay != null && parsedMonth != null) {
      return '$parsedDay/$parsedMonth';
    }
  }
  return '';
}

/// Web tip-record title. Empty day label falls back to 心水戰績.
String tipRecordTitle(Meeting? meeting) {
  if (meeting == null) return '心水戰績';
  final day = tipMeetingDayLabel(meeting);
  return day.isEmpty ? '心水戰績' : '心水戰績 · $day';
}

/// Web `tipFmtPrize` (`en-US`, no fraction digits).
String tipFmtPrize(num value) {
  final rounded = value.round();
  final negative = rounded < 0;
  final digits = rounded.abs().toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return '${negative ? '-' : ''}\$$buffer';
}

/// Web `tipFmtRate`.
String tipFmtRate(int wins, int plays) {
  if (plays == 0) return '—';
  return '${((wins / plays) * 100).toStringAsFixed(1)}%';
}

/// Web `ensureTipNoteDemoForMeeting` for one race.
///
/// Non-scratched runners that have a win price, cheapest first, then horse
/// number. At most [tipNoteMax]. Display-only: the main table has no tip column.
List<int> demoTipPicks(Race race) {
  final runners =
      [
        for (final runner in race.runners)
          if (!runner.scratched && runner.win != null) runner,
      ]..sort((a, b) {
        final byWin = a.win!.compareTo(b.win!);
        if (byWin != 0) return byWin;
        return a.no.compareTo(b.no);
      });
  final count = math.min(tipNoteMax, runners.length);
  return [for (var i = 0; i < count; i++) runners[i].no];
}

/// Web `tipRaceSettled`.
bool tipRaceSettled(Race race, {required int currentRaceNum}) {
  if (raceHasPayout(race) || race.paid) return true;
  if (!tipSettledTreatBeforeCurrentAsPaid) return false;
  return race.num < currentRaceNum;
}

/// Settled hits use the shared W/Q/P/4 circles. Unsettled picks stay plain.
CircleKind tipCircleKind(
  Race race,
  int horseNo, {
  required int currentRaceNum,
}) {
  if (!tipRaceSettled(race, currentRaceNum: currentRaceNum)) {
    return CircleKind.plain;
  }
  return kindForPick(horseNo, payoutFinishNosForRace(race));
}

double _winnerOdds(Race race, int? winnerNo) {
  if (winnerNo == null) return 8;
  for (final runner in race.runners) {
    if (runner.no != winnerNo) continue;
    final win = runner.win;
    if (win == null || win == 0) return 8;
    return win;
  }
  return 8;
}

int _poolPrize(double winOdds, double factor, double add) {
  return ((winOdds * factor + add) * tipRecordStake).round();
}

/// Web `tipEvalRace`. Unsettled or unmarked races do not count.
TipRaceEval tipEvalRace(Race race, {required int currentRaceNum}) {
  final picks = demoTipPicks(race).take(tipNoteMax).toList(growable: false);
  if (picks.isEmpty || !tipRaceSettled(race, currentRaceNum: currentRaceNum)) {
    return TipRaceEval.blank(picks);
  }
  final finish = payoutFinishNosForRace(race);
  int? at(int index) => index < finish.length ? finish[index] : null;
  final first = at(0);
  final second = at(1);
  final third = at(2);
  final fourth = at(3);
  final setAll = picks.toSet();
  final set2 = picks.take(2).toSet();
  final set3 = picks.take(3).toSet();
  final set4 = picks.take(4).toSet();
  final winHit = first != null && set2.contains(first);
  final qinHit =
      first != null &&
      second != null &&
      set3.contains(first) &&
      set3.contains(second);
  final top3Hit =
      first != null &&
      second != null &&
      third != null &&
      set4.contains(first) &&
      set4.contains(second) &&
      set4.contains(third);
  final fourthHit = fourth != null && setAll.contains(fourth);
  final tierceHit =
      first != null &&
      second != null &&
      third != null &&
      setAll.contains(first) &&
      setAll.contains(second) &&
      setAll.contains(third);
  final qplHit =
      (first != null &&
          second != null &&
          setAll.contains(first) &&
          setAll.contains(second)) ||
      (first != null &&
          third != null &&
          setAll.contains(first) &&
          setAll.contains(third)) ||
      (second != null &&
          third != null &&
          setAll.contains(second) &&
          setAll.contains(third));
  final quartetHit =
      first != null &&
      second != null &&
      third != null &&
      fourth != null &&
      setAll.contains(first) &&
      setAll.contains(second) &&
      setAll.contains(third) &&
      setAll.contains(fourth);
  final winOdds = _winnerOdds(race, first);
  return TipRaceEval(
    picks: picks,
    settled: true,
    hits: {
      'win': winHit,
      'qin': qinHit,
      'top3': top3Hit,
      'fourth': fourthHit,
      'tierce': tierceHit,
      'qpl': qplHit,
      'quartet': quartetHit,
    },
    prizes: {
      'win': winHit ? (winOdds * tipRecordStake).round() : 0,
      'qin': qinHit ? _poolPrize(winOdds, 0.55, 12) : 0,
      'top3': top3Hit ? _poolPrize(winOdds, 0.35, 18) : 0,
      'fourth': fourthHit ? (14 * tipRecordStake).round() : 0,
      'tierce': tierceHit ? _poolPrize(winOdds, 1.8, 40) : 0,
      'qpl': qplHit ? _poolPrize(winOdds, 0.4, 10) : 0,
      'quartet': quartetHit ? _poolPrize(winOdds, 2.4, 60) : 0,
    },
  );
}

/// Web `tipAggregateStats`. Both day and season skip unsettled races.
///
/// Season multiplies the day totals with the Web demo formula.
Map<String, TipStatLine> tipAggregateStats(
  Meeting meeting, {
  required int currentRaceNum,
  required String scope,
}) {
  final wins = {for (final def in tipStatDefs) def.key: 0};
  final plays = {for (final def in tipStatDefs) def.key: 0};
  final prize = {for (final def in tipStatDefs) def.key: 0};
  for (final race in meeting.races) {
    final eval = tipEvalRace(race, currentRaceNum: currentRaceNum);
    if (eval.picks.isEmpty || !eval.settled) continue;
    for (final def in tipStatDefs) {
      plays[def.key] = plays[def.key]! + 1;
      if (eval.hits[def.key] == true) {
        wins[def.key] = wins[def.key]! + 1;
      }
      prize[def.key] = prize[def.key]! + (eval.prizes[def.key] ?? 0);
    }
  }
  if (scope == 'season') {
    for (final def in tipStatDefs) {
      final nextPlays = math.max(plays[def.key]!, 1) * 6 + (def.key.length % 3);
      final nextWins = math.min(
        nextPlays,
        wins[def.key]! * 5 + (def.key.codeUnitAt(0) % 2),
      );
      plays[def.key] = nextPlays;
      wins[def.key] = nextWins;
      prize[def.key] = (prize[def.key]! * 5.2 + 120).round();
    }
  }
  return {
    for (final def in tipStatDefs)
      def.key: TipStatLine(
        wins: wins[def.key]!,
        plays: plays[def.key]!,
        prize: prize[def.key]!,
      ),
  };
}

/// Sum of the stat prizes. Web `renderTipRecordStatsHtml` total line.
int tipTotalPrize(Map<String, TipStatLine> stats) {
  var total = 0;
  for (final def in tipStatDefs) {
    total += stats[def.key]?.prize ?? 0;
  }
  return total;
}
