import 'dart:convert';

import 'package:j18pro_racecard/data/jjjc_api_config.dart';
import 'package:j18pro_racecard/data/jjjc_meeting_map.dart';
import 'package:j18pro_racecard/data/jjjc_transport.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

/// Loads a Hong Kong meeting from api_jjjc racecard + results.
///
/// Overseas days stay on [DemoMeetingRepository]. A missing base URL is not
/// this class's job; [FallbackRaceRepository] keeps the demo snapshot.
class ApiRaceRepository implements RaceRepository {
  ApiRaceRepository({required this.config, required this.transport});

  final JjjcApiConfig config;
  final JjjcTransport transport;

  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    if (!config.isConfigured) {
      throw RaceLoadException('未設定賽事接口');
    }
    if (scope != RaceCalendarScope.hk) {
      throw RaceLoadException('外地賽事尚未接入');
    }
    final venue = _venueFor(date);
    final venues = venue == null ? const ['HV', 'ST'] : [venue];
    RaceLoadException? failure;
    Meeting? empty;
    for (final code in venues) {
      try {
        final meeting = await _loadVenue(date, code);
        final race = meeting.races.first;
        final vacant = race.runners.isEmpty && race.name == '該日暫無賽事';
        if (!vacant) return meeting;
        empty ??= meeting;
      } on RaceLoadException catch (error) {
        failure = error;
      }
    }
    if (empty != null) return empty;
    throw failure ?? RaceLoadException('未能載入賽事');
  }

  Future<Meeting> _loadVenue(String date, String venue) async {
    final racecard = await _get('/api/export/racecard', date, venue);
    final results = await _get('/api/export/results', date, venue);
    return mapJjjcMeeting(
      date: date,
      venue: venue,
      racecard: racecard,
      results: results,
      silkBase: config.silkBaseUrl,
    );
  }

  Future<Map<String, dynamic>?> _get(
    String path,
    String date,
    String venue,
  ) async {
    final base = config.resolvedBase;
    final uri = Uri.parse('$base$path')
        .replace(queryParameters: {'date': date, 'venue': venue});
    final JjjcHttpResult response;
    try {
      response = await transport.get(uri, headers: config.headers);
    } on RaceLoadException {
      rethrow;
    } catch (_) {
      throw RaceLoadException('未能連線，請檢查網絡');
    }
    if (response.statusCode == 404) return null;
    if (response.statusCode >= 500) {
      throw RaceLoadException('伺服器暫時未能提供賽事');
    }
    if (response.statusCode != 200) {
      throw RaceLoadException('未能載入賽事');
    }
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is! Map) throw RaceLoadException('賽事資料格式不符');
      return Map<String, dynamic>.from(decoded);
    } on RaceLoadException {
      rethrow;
    } on FormatException {
      throw RaceLoadException('賽事資料格式不符');
    }
  }
}

/// Demo stays in front until [JjjcApiConfig.isConfigured].
/// Overseas days always use the demo stub.
class FallbackRaceRepository implements RaceRepository {
  FallbackRaceRepository({
    required this.demo,
    required this.api,
    required this.config,
  });

  final RaceRepository demo;
  final RaceRepository api;
  final JjjcApiConfig config;

  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) {
    if (!config.isConfigured || scope != RaceCalendarScope.hk) {
      return demo.load(date, scope: scope);
    }
    return api.load(date, scope: scope);
  }
}

String? _venueFor(String date) {
  final course = fixtureOn(date, RaceCalendarScope.hk)?.course;
  if (course == 'HV' || course == 'ST') return course;
  return null;
}
