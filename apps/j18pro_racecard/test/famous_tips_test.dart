import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/famous_tips/famous_tips.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'demo tipsters walk the price order and skip scratched horses',
    () async {
      final meeting = await DemoMeetingRepository().load(
        DemoMeetingRepository.snapshotDate,
      );
      final race5 = meeting.raceByNum(5)!;
      final race6 = meeting.raceByNum(6)!;
      expect(famousTipsForTipster(famousTipsters.first, race5), [6, 3, 4, 1]);
      expect(famousAggregateTips(race5), [2, 10, 5, 1, 3, 9]);
      final race6Tips = [
        for (final tipster in famousTipsters)
          ...famousTipsForTipster(tipster, race6),
      ];
      expect(race6Tips, isNot(contains(7)));
      expect(famousAggregateTips(_emptyRace()), isEmpty);
      expect(famousTipsForTipster(famousTipsters.first, null), isEmpty);
    },
  );

  test(
    'settled colours use a switch that is separate from tip-record',
    () async {
      final meeting = await DemoMeetingRepository().load(
        DemoMeetingRepository.snapshotDate,
      );
      final race1 = meeting.raceByNum(1)!;
      final race5 = meeting.raceByNum(5)!;
      expect(famousSettledTreatBeforeCurrentAsPaid, isTrue);
      expect(tipSettledTreatBeforeCurrentAsPaid, isTrue);
      expect(famousRaceSettled(race1, currentRaceNum: 5), isTrue);
      expect(famousRaceSettled(race5, currentRaceNum: 5), isFalse);
      expect(
        famousRaceSettled(
          race1,
          currentRaceNum: 5,
          treatBeforeCurrentAsPaid: false,
        ),
        isFalse,
      );
      expect(
        famousRaceSettled(
          race5.copyWith(paid: true),
          currentRaceNum: 5,
          treatBeforeCurrentAsPaid: false,
        ),
        isTrue,
      );
      expect(famousCircleKind(race1, 11, currentRaceNum: 5), CircleKind.win);
      expect(
        famousCircleKind(
          race1,
          11,
          currentRaceNum: 5,
          treatBeforeCurrentAsPaid: false,
        ),
        CircleKind.plain,
      );
      expect(famousCircleKind(race5, 6, currentRaceNum: 5), CircleKind.plain);
      expect(famousFinishTop(race1), [11, 8, 3, 4]);
    },
  );

  test('the sheet follows the global race unless a pill pins another', () {
    final meeting = buildStubMeeting('2026-10-01');
    expect(famousTipsTitle(meeting), '名家貼士 · 1/10');
    expect(famousDefaultRaceNum(meeting, 5), 1);
    expect(famousVisibleRaceNum(meeting, 5, pinnedRaceNum: 6), 1);
    expect(famousTipsTitle(null), '名家貼士');
    expect(tipFmtRate(28, 62), '45.2%');
    expect(famousTipsters, hasLength(9));
    expect(famousGroups.map((group) => group.name), ['臨場', '早餐', '馬房貼士']);
  });
}

Race _emptyRace() {
  return Race(num: 1, name: '空', time: '', meta: '', runners: const []);
}
