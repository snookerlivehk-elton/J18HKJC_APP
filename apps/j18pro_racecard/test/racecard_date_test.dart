import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'returning from a stub to the snapshot selects race 5 and clears marks',
    () async {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(racecardControllerProvider.notifier);
      await container.read(racecardControllerProvider.future);
      notifier.cycleMark(1);
      expect(
        container.read(racecardControllerProvider).requireValue.markFor(1),
        1,
      );

      await notifier.selectDate('2026-10-01');
      final stub = container.read(racecardControllerProvider).requireValue;
      expect(stub.meeting.date, '2026-10-01');
      expect(stub.currentRaceNum, 1);
      expect(stub.marks, isEmpty);

      await notifier.selectDate(DemoMeetingRepository.snapshotDate);
      final back = container.read(racecardControllerProvider).requireValue;
      expect(back.meeting.date, DemoMeetingRepository.snapshotDate);
      expect(back.currentRaceNum, 5);
      expect(back.meeting.raceByNum(5)!.runners.first.name, '本領非凡');
      expect(back.marks, isEmpty);
    },
  );

  test('a missing previous race number falls back to race 5', () async {
    final container = ProviderContainer(
      overrides: [
        raceRepositoryProvider.overrideWithValue(_RaceNumRepository()),
      ],
    );
    addTearDown(container.dispose);
    final notifier = container.read(racecardControllerProvider.notifier);
    await container.read(racecardControllerProvider.future);
    notifier.selectRace(6);
    notifier.cycleMark(1);
    expect(
      container.read(racecardControllerProvider).requireValue.currentRaceNum,
      6,
    );

    await notifier.selectDate('2026-11-11');
    final next = container.read(racecardControllerProvider).requireValue;
    expect(next.meeting.raceByNum(6), isNull);
    expect(next.currentRaceNum, 5);
    expect(next.marks, isEmpty);
  });
}

class _RaceNumRepository implements RaceRepository {
  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    final races = date == DemoMeetingRepository.snapshotDate
        ? const [1, 5, 6]
        : const [1, 5];
    return Meeting(
      date: date,
      y: '2026',
      m: '09',
      d: '23',
      weekday: '周三',
      courseLabel: '跑馬地',
      source: 'test',
      races: [
        for (final num in races)
          Race(
            num: num,
            name: '第$num場',
            time: '13:00',
            meta: '',
            runners: [
              Runner(
                no: 1,
                name: '測試馬',
                draw: 1,
                jockey: '騎',
                trainer: '練',
                win: 3,
                place: 1.5,
                scratched: false,
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
              ),
            ],
          ),
      ],
    );
  }
}
