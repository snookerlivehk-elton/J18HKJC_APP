import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

void main() {
  test('fixture lists and menu dates match the Web calendar', () {
    expect(fixturesFor(RaceCalendarScope.hk), hasLength(27));
    expect(fixturesFor(RaceCalendarScope.os), hasLength(14));
    expect(formatMenuDate('2026-09-23'), '2026/9/23 周三');
    expect(formatMenuDate('2026-10-01'), '2026/10/1 周四');
    expect(
      nearestFixtureDate('2026-09-23', RaceCalendarScope.hk),
      '2026-09-23',
    );
    expect(
      nearestFixtureDate('2026-09-23', RaceCalendarScope.os),
      '2026-09-27',
    );
  });

  test('buildStubMeeting follows the Web stub for HK and overseas days', () {
    final shaTin = buildStubMeeting('2026-10-01');
    expect(shaTin.courseLabel, '沙田');
    expect(shaTin.weekday, '周四');
    expect(shaTin.races, hasLength(1));
    expect(shaTin.races.single.num, 1);
    expect(shaTin.races.single.name, '賽事資料載入中');
    expect(shaTin.races.single.time, '13:00');
    expect(shaTin.races.single.runners, isEmpty);

    final randwick = buildStubMeeting(
      '2026-10-03',
      scope: RaceCalendarScope.os,
    );
    expect(randwick.courseLabel, '蘭域');
    expect(randwick.races.single.name, '蘭域');
    expect(randwick.races.single.runners, isEmpty);

    final ascot = buildStubMeeting('2026-09-27', scope: RaceCalendarScope.os);
    expect(ascot.courseLabel, '雅士谷');
    expect(ascot.weekday, '周日');
  });
}
