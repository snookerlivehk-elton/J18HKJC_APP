import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

/// Phase 6 will add an API implementation beside [DemoMeetingRepository].
abstract interface class RaceRepository {
  /// Loads the meeting for an ISO date (`YYYY-MM-DD`).
  ///
  /// [scope] matches Web `raceCalScope`. Hong Kong is the default.
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  });
}

class RaceLoadException implements Exception {
  RaceLoadException(this.message);

  final String message;

  @override
  String toString() => message;
}
