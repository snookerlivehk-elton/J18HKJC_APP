import 'package:j18pro_racecard/domain/meeting.dart';

/// Phase 6 will add an API implementation beside [DemoMeetingRepository].
abstract interface class RaceRepository {
  /// Loads the meeting for an ISO date (`YYYY-MM-DD`).
  Future<Meeting> load(String date);
}

class RaceLoadException implements Exception {
  RaceLoadException(this.message);

  final String message;

  @override
  String toString() => message;
}
