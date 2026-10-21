import 'dart:math' as math;

import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/index_picks.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/racecard_insight/payout_detail.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record.dart';

/// Demo switch for the famous-tips sheet only.
///
/// Default off, and separate from [tipSettledTreatBeforeCurrentAsPaid].
/// `--dart-define=J18_DEMO_FAMOUS_SETTLE_BEFORE_CURRENT=true` colours earlier
/// races again. Real dividends still colour a race when `paid` is set.
const famousSettledTreatBeforeCurrentAsPaid = bool.fromEnvironment(
  'J18_DEMO_FAMOUS_SETTLE_BEFORE_CURRENT',
  defaultValue: false,
);

const famousGroups = <FamousGroup>[
  FamousGroup(key: 'live', name: '臨場', hint: '開跑前臨場提供', earlyBonus: 0),
  FamousGroup(key: 'breakfast', name: '早餐', hint: '賽前一日或當日早上', earlyBonus: 20),
  FamousGroup(key: 'stable', name: '馬房貼士', hint: '練馬師團隊提供', earlyBonus: 10),
];

/// Web `FAMOUS_TIPSTERS_DEMO`. Distinct from the tip-record leaderboard.
const famousTipsters = <FamousTipster>[
  FamousTipster(
    id: 'fl1',
    name: '臨場神算',
    group: 'live',
    wins: 28,
    plays: 62,
    seed: 1,
    count: 4,
  ),
  FamousTipster(
    id: 'fl2',
    name: '即場追擊',
    group: 'live',
    wins: 21,
    plays: 58,
    seed: 2,
    count: 4,
  ),
  FamousTipster(
    id: 'fl3',
    name: '夜場快訊',
    group: 'live',
    wins: 19,
    plays: 54,
    seed: 3,
    count: 6,
  ),
  FamousTipster(
    id: 'fb1',
    name: '晨報心水',
    group: 'breakfast',
    wins: 24,
    plays: 70,
    seed: 4,
    count: 4,
  ),
  FamousTipster(
    id: 'fb2',
    name: '早盤精選',
    group: 'breakfast',
    wins: 18,
    plays: 66,
    seed: 5,
    count: 4,
  ),
  FamousTipster(
    id: 'fb3',
    name: '開賽早餐',
    group: 'breakfast',
    wins: 16,
    plays: 60,
    seed: 6,
    count: 5,
  ),
  FamousTipster(
    id: 'fs1',
    name: '馬房情報',
    group: 'stable',
    wins: 26,
    plays: 55,
    seed: 7,
    count: 4,
  ),
  FamousTipster(
    id: 'fs2',
    name: '練馬師消息',
    group: 'stable',
    wins: 20,
    plays: 52,
    seed: 8,
    count: 4,
  ),
  FamousTipster(
    id: 'fs3',
    name: '馬房貼士王',
    group: 'stable',
    wins: 15,
    plays: 48,
    seed: 9,
    count: 4,
  ),
];

class FamousGroup {
  const FamousGroup({
    required this.key,
    required this.name,
    required this.hint,
    required this.earlyBonus,
  });

  final String key;
  final String name;
  final String hint;
  final int earlyBonus;
}

class FamousTipster {
  const FamousTipster({
    required this.id,
    required this.name,
    required this.group,
    required this.wins,
    required this.plays,
    required this.seed,
    required this.count,
  });

  final String id;
  final String name;
  final String group;
  final int wins;
  final int plays;
  final int seed;
  final int count;
}

/// Web famous-tips title. The menu item stays「名家」.
String famousTipsTitle(Meeting? meeting) {
  if (meeting == null) return '名家貼士';
  final day = tipMeetingDayLabel(meeting);
  return day.isEmpty ? '名家貼士' : '名家貼士 · $day';
}

/// Web `famousTipsRaceNum` when the sheet has not pinned another race.
int famousDefaultRaceNum(Meeting? meeting, int currentRaceNum) {
  final races = meeting?.races ?? const <Race>[];
  if (races.any((race) => race.num == currentRaceNum)) return currentRaceNum;
  if (races.isEmpty) return 1;
  return races.first.num;
}

/// The race shown in the sheet. A pinned number wins when that race exists.
int famousVisibleRaceNum(
  Meeting? meeting,
  int currentRaceNum, {
  int? pinnedRaceNum,
}) {
  final races = meeting?.races ?? const <Race>[];
  if (pinnedRaceNum != null && races.any((race) => race.num == pinnedRaceNum)) {
    return pinnedRaceNum;
  }
  return famousDefaultRaceNum(meeting, currentRaceNum);
}

/// Paid races are settled. Earlier races are settled only while the demo switch is on.
bool famousRaceSettled(
  Race race, {
  required int currentRaceNum,
  bool treatBeforeCurrentAsPaid = famousSettledTreatBeforeCurrentAsPaid,
}) {
  if (raceHasPayout(race) || race.paid) return true;
  if (!treatBeforeCurrentAsPaid) return false;
  return race.num < currentRaceNum;
}

CircleKind famousCircleKind(
  Race race,
  int horseNo, {
  required int currentRaceNum,
  bool treatBeforeCurrentAsPaid = famousSettledTreatBeforeCurrentAsPaid,
}) {
  if (!famousRaceSettled(
    race,
    currentRaceNum: currentRaceNum,
    treatBeforeCurrentAsPaid: treatBeforeCurrentAsPaid,
  )) {
    return CircleKind.plain;
  }
  return kindForPick(horseNo, payoutFinishNosForRace(race));
}

/// Web `famousTipsForTipster`. Scratched runners and missing win prices are left out.
List<int> famousTipsForTipster(FamousTipster tipster, Race? race) {
  if (race == null) return const [];
  final runners =
      [
        for (final runner in race.runners)
          if (!runner.scratched && runner.win != null) runner,
      ]..sort((a, b) {
        final byWin = a.win!.compareTo(b.win!);
        if (byWin != 0) return byWin;
        return a.no.compareTo(b.no);
      });
  if (runners.isEmpty) return const [];
  final capped = math.min(6, math.max(1, tipster.count));
  final maxCount = math.min(capped, runners.length);
  final start = tipster.seed % runners.length;
  final out = <int>[];
  final seen = <int>{};
  for (var i = 0; i < runners.length && out.length < maxCount; i++) {
    final row = runners[(start + i * 2) % runners.length];
    if (seen.add(row.no)) out.add(row.no);
  }
  for (var j = 0; j < runners.length && out.length < maxCount; j++) {
    if (seen.add(runners[j].no)) out.add(runners[j].no);
  }
  return out;
}

int famousGroupEarlyBonus(String groupKey) {
  for (final group in famousGroups) {
    if (group.key == groupKey) return group.earlyBonus;
  }
  return 0;
}

/// First four finish numbers. Empty when the caller has not decided the race is settled.
List<int> famousFinishTop(Race race) {
  return payoutFinishNosForRace(race).take(4).toList(growable: false);
}

/// Web `famousAggregateTips`. At most six numbers.
List<int> famousAggregateTips(Race? race) {
  if (race == null) return const [];
  final tally = <int, _FamousTally>{};
  for (final tipster in famousTipsters) {
    final tips = famousTipsForTipster(tipster, race);
    final earlyBonus = famousGroupEarlyBonus(tipster.group);
    for (var index = 0; index < tips.length; index++) {
      final no = tips[index];
      final row = tally.putIfAbsent(no, () => _FamousTally(no));
      row.votes += 1;
      row.early += (10 - index) + earlyBonus;
    }
  }
  final ranked = tally.values.toList()
    ..sort((a, b) {
      if (a.votes != b.votes) return b.votes.compareTo(a.votes);
      if (a.early != b.early) return b.early.compareTo(a.early);
      return a.no.compareTo(b.no);
    });
  final count = math.min(6, ranked.length);
  return [for (var i = 0; i < count; i++) ranked[i].no];
}

class _FamousTally {
  _FamousTally(this.no);

  final int no;
  var votes = 0;
  var early = 0;
}
