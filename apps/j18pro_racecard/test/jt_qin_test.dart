import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/jt_collab/jt_collab.dart';
import 'package:j18pro_racecard/features/qin/qin_board.dart';

Runner _runner(
  int no, {
  double? win,
  double? place,
  bool scratched = false,
  String jockey = '騎師',
  String trainer = '練馬師',
}) {
  return Runner(
    no: no,
    name: '馬$no',
    draw: 1,
    jockey: jockey,
    trainer: trainer,
    win: win,
    place: place,
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
  );
}

Race _race(int num, List<Runner> runners) {
  return Race(
    num: num,
    name: '測試',
    time: '18:00',
    meta: '1200米',
    runners: runners,
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('partnership demo matches the web seed', () async {
    final meeting = await DemoMeetingRepository().load(
      DemoMeetingRepository.snapshotDate,
    );
    final horse = meeting.raceByNum(5)!.runners.firstWhere((r) => r.no == 1);
    final demo = jtCollabDemo(
      horseNo: horse.no,
      raceNum: 5,
      jockeyRaw: horse.jockey,
      trainerRaw: horse.trainer,
    );
    expect(demo.jockey, '何澤堯');
    expect(demo.trainer, '羅富全');
    expect(demo.pair, '何澤堯 × 羅富全');
    expect(demo.summary, '近季合作：12 仗 · 0冠 0亞 0季 · 勝率 0.0% · 位置率 0.0%');
    expect(demo.races, hasLength(6));
    expect(demo.races.first.date, '2026-09-03');
    expect(demo.races.first.course, '沙田');
    expect(demo.races.first.dist, '1400米');
    expect(demo.races.first.finishLabel, '第5名');

    final allowed = jtPersonName('周俊樂 (-2)');
    expect(allowed, '周俊樂');
    expect(
      jtCollabDemo(
        horseNo: 1,
        raceNum: 1,
        jockeyRaw: '—',
        trainerRaw: '',
      ).hasPeople,
      isFalse,
    );
  });

  test('qin odds, index, hot pair, and scratch follow the web formula', () {
    final race = _race(5, [
      _runner(1, win: 12, place: 4.2),
      _runner(2, win: 10, place: 3),
      _runner(7, win: 37, place: 8, scratched: true),
    ]);
    final qin = buildQinBoard(race, QinMode.qin);
    final pair = qin.pair(1, 2)!;
    expect(fmtQinOdds(pair.odds), '31');
    expect(pair.index, inInclusiveRange(70, 92));
    expect(pair.hot, isTrue);
    expect(qin.hotKey, '1-2');
    expect(qin.pair(1, 7)!.scratched, isTrue);
    expect(fmtQinOdds(qin.pair(1, 7)!.odds), '—');
    expect(qin.pair(2, 7)!.odds, isNull);

    final place = buildQinBoard(race, QinMode.qpl);
    expect(fmtQinOdds(place.pair(1, 2)!.odds), isNot('31'));
    expect(place.pair(1, 2)!.odds, isNotNull);

    expect(synthComboOdds(null, 2, 0.26), isNull);
    expect(synthComboOdds(100, 100, 0.26), 999);
    expect(fmtQinOdds(20), '20');
    expect(fmtQinOdds(20.5), '20.5');
    expect(synthQinIndex(1), 92);
  });
}
