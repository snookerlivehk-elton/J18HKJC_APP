import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';

/// Web demo opens on race 5 (`let currentRace = 5`).
const demoInitialRaceNum = 5;

final raceRepositoryProvider = Provider<RaceRepository>((ref) {
  return DemoMeetingRepository();
});

final racecardControllerProvider =
    AsyncNotifierProvider<RacecardController, RacecardViewState>(
  RacecardController.new,
);

@immutable
class RacecardViewState {
  const RacecardViewState({
    required this.meeting,
    required this.currentRaceNum,
    this.marks = const {},
  });

  final Meeting meeting;
  final int currentRaceNum;

  /// Swallowtail state keyed `raceNum:horseNo`. 1 yellow, 2 green. Missing is none.
  final Map<String, int> marks;

  Race get currentRace {
    final race = meeting.raceByNum(currentRaceNum);
    if (race == null) {
      throw StateError('場次 $currentRaceNum 不在會議內');
    }
    return race;
  }

  int markFor(int horseNo) {
    final mark = marks['$currentRaceNum:$horseNo'] ?? 0;
    if (mark == 1 || mark == 2) return mark;
    return 0;
  }

  RacecardViewState copyWith({
    int? currentRaceNum,
    Map<String, int>? marks,
  }) {
    return RacecardViewState(
      meeting: meeting,
      currentRaceNum: currentRaceNum ?? this.currentRaceNum,
      marks: marks ?? this.marks,
    );
  }

  @override
  bool operator ==(Object other) {
    return other is RacecardViewState &&
        meeting == other.meeting &&
        currentRaceNum == other.currentRaceNum &&
        mapEquals(marks, other.marks);
  }

  @override
  int get hashCode => Object.hash(
        meeting,
        currentRaceNum,
        Object.hashAllUnordered([
          for (final entry in marks.entries) Object.hash(entry.key, entry.value),
        ]),
      );
}

class RacecardController extends AsyncNotifier<RacecardViewState> {
  @override
  Future<RacecardViewState> build() async {
    final meeting = await ref.watch(raceRepositoryProvider).load(
          DemoMeetingRepository.snapshotDate,
        );
    final initial = meeting.raceByNum(demoInitialRaceNum) != null
        ? demoInitialRaceNum
        : meeting.races.first.num;
    return RacecardViewState(meeting: meeting, currentRaceNum: initial);
  }

  void selectRace(int raceNum) {
    final value = state.asData?.value;
    if (value == null) return;
    if (value.meeting.raceByNum(raceNum) == null) return;
    if (value.currentRaceNum == raceNum) return;
    state = AsyncData(value.copyWith(currentRaceNum: raceNum));
  }

  /// None → yellow → green → none. Marks stay when the visible race changes.
  void cycleMark(int horseNo) {
    final value = state.asData?.value;
    if (value == null) return;
    final exists = value.currentRace.runners.any((runner) => runner.no == horseNo);
    if (!exists) return;
    final key = '${value.currentRaceNum}:$horseNo';
    final next = ((value.marks[key] ?? 0) + 1) % 3;
    final updated = Map<String, int>.of(value.marks);
    if (next == 0) {
      updated.remove(key);
    } else {
      updated[key] = next;
    }
    state = AsyncData(value.copyWith(marks: Map.unmodifiable(updated)));
  }
}
