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
  });

  final Meeting meeting;
  final int currentRaceNum;

  Race get currentRace {
    final race = meeting.raceByNum(currentRaceNum);
    if (race == null) {
      throw StateError('場次 $currentRaceNum 不在會議內');
    }
    return race;
  }

  RacecardViewState copyWith({int? currentRaceNum}) {
    return RacecardViewState(
      meeting: meeting,
      currentRaceNum: currentRaceNum ?? this.currentRaceNum,
    );
  }
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
}
