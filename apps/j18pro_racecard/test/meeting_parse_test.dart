import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('parses the Web MEETING fixture', () async {
    final raw = await rootBundle.loadString(DemoMeetingRepository.assetPath);
    final meeting = Meeting.fromJson(jsonDecode(raw) as Map<String, dynamic>);

    expect(meeting.date, '2026-09-23');
    expect(meeting.courseLabel, '跑馬地');
    expect(meeting.races.map((race) => race.num), [1, 5, 6]);

    final race1 = meeting.raceByNum(1)!;
    expect(race1.name, '南風讓賽');
    expect(race1.runners, hasLength(12));
    final first = race1.runners.first;
    expect(first.no, 1);
    expect(first.name, '堅多福');
    expect(first.draw, 12);
    expect(first.jockey, '何澤堯');
    expect(first.trainer, '方嘉柏');
    expect(first.win, 13);
    expect(first.place, 4);
    expect(first.scratched, isFalse);
    expect(first.gear, isNull);
    expect(first.silk, contains('RaceColor'));

    final race5 = meeting.raceByNum(5)!;
    expect(race5.runners, hasLength(11));
    expect(race5.runners.first.name, '本領非凡');
    expect(race5.runners.first.win, 12);
    expect(race5.runners.first.place, 4.2);

    final race6 = meeting.raceByNum(6)!;
    expect(race6.runners, hasLength(10));
    expect(race6.runners.map((runner) => runner.no), [
      1,
      2,
      3,
      4,
      5,
      6,
      7,
      8,
      9,
      10,
    ]);
    final scratched = race6.runners.singleWhere((runner) => runner.no == 7);
    expect(scratched.name, '雙劍合璧');
    expect(scratched.scratched, isTrue);
    expect(scratched.win, isNull);
    expect(scratched.place, isNull);
    expect(race6.runners.where((runner) => runner.scratched), hasLength(1));
  });

  test('formatOdds trims whole numbers and keeps one decimal', () {
    expect(formatOdds(13), '13');
    expect(formatOdds(8.9), '8.9');
    expect(formatOdds(4.2), '4.2');
    expect(formatOdds(null), '—');
  });

  test('rejects a runner without a name', () {
    expect(() => Runner.fromJson({'no': 1, 'draw': 1}), throwsFormatException);
  });

  test(
    'DemoMeetingRepository caches the snapshot and stubs other dates',
    () async {
      final repository = DemoMeetingRepository();
      final meeting = await repository.load(DemoMeetingRepository.snapshotDate);
      expect(meeting.races, hasLength(3));
      final again = await repository.load(DemoMeetingRepository.snapshotDate);
      expect(identical(meeting, again), isTrue);

      final stub = await repository.load('2026-01-01');
      expect(stub.date, '2026-01-01');
      expect(stub.courseLabel, isEmpty);
      expect(stub.races, hasLength(1));
      expect(stub.races.single.name, '賽事資料載入中');
      expect(stub.races.single.runners, isEmpty);

      final overseas = await repository.load(
        '2026-09-27',
        scope: RaceCalendarScope.os,
      );
      expect(overseas.courseLabel, '雅士谷');
      expect(overseas.races.single.runners, isEmpty);
    },
  );
}
