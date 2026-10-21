import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/data/api_race_repository.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/data/jjjc_api_config.dart';
import 'package:j18pro_racecard/data/jjjc_transport.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/index_picks.dart';
import 'package:j18pro_racecard/features/racecard_insight/time_scrub.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

/// Web demo opens on race 5 (`let currentRace = 5`).
const demoInitialRaceNum = 5;

/// Web `capsuleActive`. Only one capsule body is open.
enum OpenCapsule { picks, payout }

/// Web `indexStrategyPinned` default.
const defaultIndexStrategyId = 'composite';

final jjjcApiConfigProvider = Provider<JjjcApiConfig>((ref) {
  return JjjcApiConfig.fromEnvironment();
});

final jjjcTransportProvider = Provider<JjjcTransport>((ref) {
  return HttpJjjcTransport();
});

/// Demo snapshot until `JJJC_API_BASE` (or `JJJC_RESULTS_API_BASE`) is set.
final raceRepositoryProvider = Provider<RaceRepository>((ref) {
  final config = ref.watch(jjjcApiConfigProvider);
  final demo = DemoMeetingRepository();
  if (!config.isConfigured) return demo;
  return FallbackRaceRepository(
    demo: demo,
    api: ApiRaceRepository(
      config: config,
      transport: ref.watch(jjjcTransportProvider),
    ),
    config: config,
  );
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
    this.scrubPointIdx = -1,
    this.openCapsule = OpenCapsule.picks,
    this.capsuleDropOpen = false,
    this.indexStrategyId = defaultIndexStrategyId,
    this.calendarScope = RaceCalendarScope.hk,
  });

  final Meeting meeting;
  final int currentRaceNum;

  /// Web `raceCalScope` of the meeting currently on the table.
  final RaceCalendarScope calendarScope;

  /// Swallowtail state keyed `raceNum:horseNo`. 1 yellow, 2 green. Missing is none.
  final Map<String, int> marks;

  /// Web `scrubPointIdx`. `-1` follows the latest point (0').
  final int scrubPointIdx;

  /// Which capsule body is expanded. The other stays closed.
  final OpenCapsule openCapsule;

  /// Chevron drop (strategy list or per-race payout). Independent of the body.
  final bool capsuleDropOpen;

  /// Web `indexStrategyPinned`.
  final String indexStrategyId;

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
    Meeting? meeting,
    int? currentRaceNum,
    Map<String, int>? marks,
    int? scrubPointIdx,
    OpenCapsule? openCapsule,
    bool? capsuleDropOpen,
    String? indexStrategyId,
    RaceCalendarScope? calendarScope,
  }) {
    return RacecardViewState(
      meeting: meeting ?? this.meeting,
      currentRaceNum: currentRaceNum ?? this.currentRaceNum,
      marks: marks ?? this.marks,
      scrubPointIdx: scrubPointIdx ?? this.scrubPointIdx,
      openCapsule: openCapsule ?? this.openCapsule,
      capsuleDropOpen: capsuleDropOpen ?? this.capsuleDropOpen,
      indexStrategyId: indexStrategyId ?? this.indexStrategyId,
      calendarScope: calendarScope ?? this.calendarScope,
    );
  }

  @override
  bool operator ==(Object other) {
    return other is RacecardViewState &&
        meeting == other.meeting &&
        currentRaceNum == other.currentRaceNum &&
        calendarScope == other.calendarScope &&
        scrubPointIdx == other.scrubPointIdx &&
        openCapsule == other.openCapsule &&
        capsuleDropOpen == other.capsuleDropOpen &&
        indexStrategyId == other.indexStrategyId &&
        mapEquals(marks, other.marks);
  }

  @override
  int get hashCode => Object.hash(
    meeting,
    currentRaceNum,
    calendarScope,
    scrubPointIdx,
    openCapsule,
    capsuleDropOpen,
    indexStrategyId,
    Object.hashAllUnordered([
      for (final entry in marks.entries) Object.hash(entry.key, entry.value),
    ]),
  );
}

class RacecardController extends AsyncNotifier<RacecardViewState> {
  @override
  Future<RacecardViewState> build() async {
    final meeting = await ref
        .watch(raceRepositoryProvider)
        .load(DemoMeetingRepository.snapshotDate);
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
    // Marks, scrub index, and the open capsule stay. Web `selectRace` does not
    // reset `scrubPointIdx` or `rowMarks`.
    state = AsyncData(value.copyWith(currentRaceNum: raceNum));
  }

  /// Clamps onto the static scrub marks. Does not use `-1`.
  void setScrubIndex(int index) {
    final value = state.asData?.value;
    if (value == null) return;
    final next = index.clamp(0, scrubMarkCount - 1);
    if (value.scrubPointIdx == next) return;
    state = AsyncData(value.copyWith(scrubPointIdx: next));
  }

  /// Switches the open body. Switching closes the drop; tapping the open body
  /// is handled by [toggleCapsuleDrop].
  void selectCapsule(OpenCapsule which) {
    final value = state.asData?.value;
    if (value == null) return;
    if (value.openCapsule == which) return;
    state = AsyncData(
      value.copyWith(openCapsule: which, capsuleDropOpen: false),
    );
  }

  void toggleCapsuleDrop() {
    final value = state.asData?.value;
    if (value == null) return;
    state = AsyncData(value.copyWith(capsuleDropOpen: !value.capsuleDropOpen));
  }

  /// Web `setIndexStrategyPinned`: a new strategy clears the scrub back to latest.
  void setIndexStrategy(String id) {
    final value = state.asData?.value;
    if (value == null) return;
    final next = canonicalIndexStrategyId(id);
    if (next == value.indexStrategyId) return;
    state = AsyncData(value.copyWith(indexStrategyId: next, scrubPointIdx: -1));
  }

  /// Web `loadMeetingForDate`. Replaces the table's meeting. Marks reset
  /// because horse numbers belong to the previous card.
  Future<void> selectDate(
    String iso, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    final latest = state.asData?.value;
    if (latest == null) return;
    if (latest.meeting.date == iso && latest.calendarScope == scope) return;
    state = const AsyncLoading();
    final Meeting meeting;
    try {
      meeting = await ref.read(raceRepositoryProvider).load(iso, scope: scope);
    } on RaceLoadException catch (error, stack) {
      state = AsyncError(error, stack);
      return;
    } catch (error, stack) {
      state = AsyncError(RaceLoadException('未能載入賽事'), stack);
      return;
    }
    if (meeting.races.isEmpty) {
      state = AsyncError(RaceLoadException('該日暫無賽事'), StackTrace.current);
      return;
    }
    final fromStub =
        latest.meeting.date != DemoMeetingRepository.snapshotDate ||
        latest.calendarScope != RaceCalendarScope.hk;
    final toSnapshot =
        iso == DemoMeetingRepository.snapshotDate &&
        scope == RaceCalendarScope.hk;
    final previous = meeting.raceByNum(latest.currentRaceNum);
    // Web opens on race 5. A stub only has race 1, so keeping that number
    // would hide the snapshot's default race after coming back.
    final preferDefault = previous == null || (fromStub && toSnapshot);
    final raceNum =
        preferDefault && meeting.raceByNum(demoInitialRaceNum) != null
        ? demoInitialRaceNum
        : previous != null
        ? latest.currentRaceNum
        : meeting.races.first.num;
    state = AsyncData(
      latest.copyWith(
        meeting: meeting,
        currentRaceNum: raceNum,
        calendarScope: scope,
        marks: const {},
        scrubPointIdx: -1,
        capsuleDropOpen: false,
      ),
    );
  }

  /// Web `openPayoutForRace`: jump to that race, open the payout capsule, close the drop.
  void openPayoutForRace(int raceNum) {
    final value = state.asData?.value;
    if (value == null) return;
    if (value.meeting.raceByNum(raceNum) == null) return;
    state = AsyncData(
      value.copyWith(
        currentRaceNum: raceNum,
        openCapsule: OpenCapsule.payout,
        capsuleDropOpen: false,
      ),
    );
  }

  /// None → yellow → green → none. Marks stay when the visible race changes.
  void cycleMark(int horseNo) {
    final value = state.asData?.value;
    if (value == null) return;
    final exists = value.currentRace.runners.any(
      (runner) => runner.no == horseNo,
    );
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
