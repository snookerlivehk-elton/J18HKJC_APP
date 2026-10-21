import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record.dart';

Runner _runner(int no, double? win, {bool scratched = false, int? finish}) {
  return Runner(
    no: no,
    name: '馬$no',
    draw: 1,
    jockey: '',
    trainer: '',
    win: win,
    place: null,
    scratched: scratched,
    silk: null,
    form6: null,
    recent: null,
    age: null,
    rating: null,
    rtgDelta: null,
    hw: null,
    bodyWt: null,
    gear: null,
    career: null,
    rail: null,
    dam: null,
    sire: null,
    damsire: null,
    owner: null,
    prize: null,
    finish: finish,
  );
}

Race _race(int num, List<Runner> runners, {bool paid = false}) {
  return Race(
    num: num,
    name: '測試',
    time: '18:40',
    meta: '',
    runners: runners,
    paid: paid,
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('demo picks are the six shortest prices, scratched excluded', () async {
    final meeting = await DemoMeetingRepository().load(
      DemoMeetingRepository.snapshotDate,
    );
    final race1 = meeting.raceByNum(1)!;
    expect(demoTipPicks(race1), [11, 8, 3, 4, 6, 1]);

    final race6 = meeting.raceByNum(6)!;
    final picks6 = demoTipPicks(race6);
    expect(picks6, [4, 1, 5, 9, 6, 3]);
    expect(picks6, isNot(contains(7)));

    final empty = _race(1, const []);
    expect(demoTipPicks(empty), isEmpty);
    expect(
      demoTipPicks(
        _race(1, [_runner(1, null), _runner(2, 1.2, scratched: true)]),
      ),
      isEmpty,
    );
  });

  test(
    'races before the current race are settled; later races stay plain',
    () async {
      final meeting = await DemoMeetingRepository().load(
        DemoMeetingRepository.snapshotDate,
      );
      final race1 = meeting.raceByNum(1)!;
      final race5 = meeting.raceByNum(5)!;
      final race6 = meeting.raceByNum(6)!;

      expect(tipRaceSettled(race1, currentRaceNum: 5), isTrue);
      expect(tipRaceSettled(race5, currentRaceNum: 5), isFalse);
      expect(tipRaceSettled(race6, currentRaceNum: 5), isFalse);
      expect(tipCircleKind(race1, 11, currentRaceNum: 5), CircleKind.win);
      expect(tipCircleKind(race1, 8, currentRaceNum: 5), CircleKind.quinella);
      expect(tipCircleKind(race1, 3, currentRaceNum: 5), CircleKind.place);
      expect(tipCircleKind(race1, 4, currentRaceNum: 5), CircleKind.fourth);
      expect(tipCircleKind(race1, 6, currentRaceNum: 5), CircleKind.plain);
      expect(tipCircleKind(race5, 5, currentRaceNum: 5), CircleKind.plain);

      final paidLater = race6.copyWith(paid: true);
      expect(tipRaceSettled(paidLater, currentRaceNum: 5), isTrue);
    },
  );

  test('finish order colours circles, not the pick order', () {
    final race = _race(2, [
      _runner(1, 2, finish: 4),
      _runner(2, 3, finish: 1),
      _runner(3, 9, finish: 2),
      _runner(4, 10, finish: 3),
      _runner(5, 11, finish: 5),
    ], paid: true);
    expect(demoTipPicks(race), [1, 2, 3, 4, 5]);
    expect(tipCircleKind(race, 1, currentRaceNum: 9), CircleKind.fourth);
    expect(tipCircleKind(race, 2, currentRaceNum: 9), CircleKind.win);
    final eval = tipEvalRace(race, currentRaceNum: 9);
    expect(eval.settled, isTrue);
    expect(eval.hits['win'], isTrue);
    expect(eval.prizes['win'], 30);
  });

  test('day stats count only the settled snapshot race', () async {
    final meeting = await DemoMeetingRepository().load(
      DemoMeetingRepository.snapshotDate,
    );
    final day = tipAggregateStats(meeting, currentRaceNum: 5, scope: 'day');
    expect(day['win']!.plays, 1);
    expect(day['win']!.wins, 1);
    expect(day['win']!.prize, 34);
    expect(tipFmtRate(day['win']!.wins, day['win']!.plays), '100.0%');
    expect(day['qin']!.prize, 139);
    expect(day['top3']!.prize, 192);
    expect(day['fourth']!.prize, 140);
    expect(day['tierce']!.prize, 461);
    expect(day['qpl']!.prize, 114);
    expect(day['quartet']!.prize, 682);
    expect(tipFmtPrize(tipTotalPrize(day)), r'$1,762');

    final season = tipAggregateStats(
      meeting,
      currentRaceNum: 5,
      scope: 'season',
    );
    expect(season['win']!.plays, 6);
    expect(season['win']!.wins, 6);
    expect(season['top3']!.plays, 7);
    expect(season['top3']!.wins, 5);
    expect(tipFmtRate(season['top3']!.wins, season['top3']!.plays), '71.4%');
    expect(season['top3']!.prize, 1118);
    expect(tipFmtPrize(tipTotalPrize(season)), r'$10,002');
    expect(season['win']!.plays, isNot(day['win']!.plays));
  });

  test('an empty stub meeting has dashes today and a season multiplier', () {
    final meeting = buildStubMeeting('2026-10-01');
    expect(tipRecordTitle(meeting), '心水戰績 · 1/10');
    expect(tipMeetingDayLabel(meeting), '1/10');
    final day = tipAggregateStats(meeting, currentRaceNum: 1, scope: 'day');
    expect(day['win']!.plays, 0);
    expect(tipFmtRate(0, 0), '—');
    expect(tipFmtPrize(tipTotalPrize(day)), r'$0');

    final season = tipAggregateStats(
      meeting,
      currentRaceNum: 1,
      scope: 'season',
    );
    expect(season['win']!.plays, 6);
    expect(season['win']!.wins, 1);
    expect(season['win']!.prize, 120);
    expect(season['top3']!.wins, 0);
    expect(tipFmtRate(season['top3']!.wins, season['top3']!.plays), '0.0%');
  });

  test('prize format and leaderboard headline stay on the demo table', () {
    expect(tipFmtPrize(18640), r'$18,640');
    expect(tipFmtPrize(0), r'$0');
    expect(tipLeaderboard, hasLength(10));
    expect(tipLeaderboard.first.name, '谷草快手');
    expect(tipLeaderboard.first.prize, 18640);
    expect(tipLeaderboard.last.name, '長途耐力');
    final triple = tipStatTriple(tipLeaderboard.first.stats['win']);
    expect(triple.wins, 18);
    expect(triple.plays, 42);
    expect(triple.prize, 5200);
    expect(tipFmtRate(18, 42), '42.9%');
    expect(tipRecordTitle(null), '心水戰績');
  });
}
