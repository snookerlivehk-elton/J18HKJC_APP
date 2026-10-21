import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

/// Serves the bundled Web `MEETING` extract for the snapshot date.
/// Every other date is a Web `buildStubMeeting` (no runners).
class DemoMeetingRepository implements RaceRepository {
  DemoMeetingRepository({AssetBundle? bundle}) : _bundle = bundle ?? rootBundle;

  static const snapshotDate = '2026-09-23';
  static const assetPath = 'assets/fixtures/meeting_20260923.json';

  final AssetBundle _bundle;
  Meeting? _cached;

  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    if (scope != RaceCalendarScope.hk || date != snapshotDate) {
      return buildStubMeeting(date, scope: scope);
    }
    final cached = _cached;
    if (cached != null) return cached;
    // `cache: false` so a future completed in one widget-test zone is not
    // awaited again from the next test (that shared future never resumes).
    final raw = await _bundle.loadString(assetPath, cache: false);
    final decoded = jsonDecode(raw);
    if (decoded is! Map) {
      throw const FormatException('賽事資料不是物件');
    }
    final meeting = Meeting.fromJson(Map<String, dynamic>.from(decoded));
    _cached = meeting;
    return meeting;
  }
}
