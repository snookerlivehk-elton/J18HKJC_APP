import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/data/api_race_repository.dart';
import 'package:j18pro_racecard/data/demo_meeting_repository.dart';
import 'package:j18pro_racecard/data/jjjc_api_config.dart';
import 'package:j18pro_racecard/data/jjjc_meeting_map.dart';
import 'package:j18pro_racecard/data/jjjc_transport.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

Map<String, dynamic> _jsonFile(String path) {
  final decoded = jsonDecode(File(path).readAsStringSync());
  return Map<String, dynamic>.from(decoded as Map);
}

class _ScriptedTransport implements JjjcTransport {
  _ScriptedTransport(this.handler);

  final JjjcHttpResult Function(Uri uri) handler;
  final uris = <Uri>[];

  @override
  Future<JjjcHttpResult> get(Uri uri, {Map<String, String>? headers}) async {
    uris.add(uri);
    return handler(uri);
  }
}

class _CountingRepository implements RaceRepository {
  _CountingRepository(this.meeting);

  final Meeting meeting;
  var calls = 0;

  @override
  Future<Meeting> load(
    String date, {
    RaceCalendarScope scope = RaceCalendarScope.hk,
  }) async {
    calls += 1;
    return meeting;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('2026-09-23 race 1 matches the demo snapshot horse list', () async {
    final card = _jsonFile('test/fixtures/jjjc_racecard_HV_20260923_R1.json');
    final results = _jsonFile('test/fixtures/jjjc_results_HV_20260923_R1.json');
    final mapped = mapJjjcMeeting(
      date: '2026-09-23',
      venue: 'HV',
      racecard: card,
      results: results,
    );
    final demo = await DemoMeetingRepository().load('2026-09-23');
    final apiRunners = mapped.raceByNum(1)!.runners;
    final demoRunners = demo.raceByNum(1)!.runners;
    expect(apiRunners.map((runner) => runner.no), [
      for (final runner in demoRunners) runner.no,
    ]);
    expect(apiRunners.map((runner) => runner.name), [
      for (final runner in demoRunners) runner.name,
    ]);
    expect(apiRunners, hasLength(12));
    expect(mapped.courseLabel, '跑馬地');
    final first = apiRunners.first;
    expect(first.name, '堅多福');
    expect(first.win, 18);
    expect(first.place, isNull);
    expect(first.silk, endsWith('/K306.gif'));
    expect(first.jockey, '何澤堯');
    expect(mapped.raceByNum(1)!.paid, isTrue);
    expect(
      mapped.raceByNum(1)!.dividends!.map((row) => row.pool),
      contains('獨贏'),
    );
  });

  test('contract sample keeps chinese names and drops HV horse 13', () {
    final card = _jsonFile('../../fixtures/jjjc_racecard_HV_20260909_R1.json');
    final results = {
      'schema': 'jjjc.results.v1',
      'races': [
        {
          'race_no': 1,
          'race_name': 'ADMIRALTY HANDICAP',
          'runners': [
            {
              'horse_no': 1,
              'horse_name': 'FLASH STAR',
              'jockey_name': 'H Bowman',
              'trainer_name': 'C S Shum',
              'win_odds': 4.5,
              'finish_order_num': 1,
              'finishing_position': 1,
            },
            {
              'horse_no': 13,
              'horse_name': 'GHOST',
              'win_odds': 99,
              'finish_order_num': 2,
            },
          ],
          'dividends': [
            {
              'pool': 'Pool',
              'amount': null,
              'combination': 'Winning Combination',
            },
            {'pool': 'WIN', 'amount': 45, 'combination': '1'},
          ],
        },
      ],
    };
    final meeting = mapJjjcMeeting(
      date: '2026-09-09',
      venue: 'HV',
      racecard: card,
      results: results,
    );
    final runners = meeting.raceByNum(1)!.runners;
    expect(runners.map((runner) => runner.no), [1, 2]);
    expect(runners.first.name, '閃電星福');
    expect(runners.first.jockey, '布文');
    expect(runners.first.win, 4.5);
    expect(meeting.raceByNum(1)!.dividends!.single.pool, '獨贏');
    expect(meeting.raceByNum(1)!.dividends!.single.pay, 45);
  });

  test('empty exports become an empty race day', () {
    final meeting = mapJjjcMeeting(
      date: '2026-10-01',
      venue: 'ST',
      racecard: {'schema': 'jjjc.racecard.v1', 'races': []},
      results: {'schema': 'jjjc.results.v1', 'races': []},
    );
    expect(meeting.courseLabel, '沙田');
    expect(meeting.races.single.name, '該日暫無賽事');
    expect(meeting.races.single.runners, isEmpty);
  });

  test('bad schema and unavailable status are explicit failures', () {
    expect(
      () => mapJjjcMeeting(
        date: '2026-09-23',
        venue: 'HV',
        racecard: {'schema': 'jjjc.other.v9', 'races': []},
      ),
      throwsA(
        isA<RaceLoadException>().having(
          (error) => error.message,
          'message',
          '賽事資料格式不符',
        ),
      ),
    );
    expect(
      () => mapJjjcMeeting(
        date: '2026-09-23',
        venue: 'HV',
        results: {'schema': 'jjjc.results.v1', 'status': 'unavailable'},
      ),
      throwsA(
        isA<RaceLoadException>().having(
          (error) => error.message,
          'message',
          '伺服器暫時未能提供賽事',
        ),
      ),
    );
  });

  test(
    'repository surfaces http failures and keeps demo when unconfigured',
    () async {
      final transport = _ScriptedTransport((uri) {
        if (uri.path.endsWith('/results')) {
          return const JjjcHttpResult(statusCode: 500, body: '');
        }
        return const JjjcHttpResult(
          statusCode: 200,
          body: '{"schema":"jjjc.racecard.v1","races":[]}',
        );
      });
      final api = ApiRaceRepository(
        config: const JjjcApiConfig(baseUrl: 'https://apicc.up.railway.app'),
        transport: transport,
      );
      expect(
        () => api.load('2026-09-23'),
        throwsA(
          isA<RaceLoadException>().having(
            (error) => error.message,
            'message',
            '伺服器暫時未能提供賽事',
          ),
        ),
      );

      final offline = _ScriptedTransport((uri) {
        throw RaceLoadException('未能連線，請檢查網絡');
      });
      expect(
        () => ApiRaceRepository(
          config: const JjjcApiConfig(baseUrl: 'https://apicc.up.railway.app'),
          transport: offline,
        ).load('2026-09-23'),
        throwsA(
          isA<RaceLoadException>().having(
            (error) => error.message,
            'message',
            '未能連線，請檢查網絡',
          ),
        ),
      );

      final demo = DemoMeetingRepository();
      final counting = _CountingRepository(
        Meeting(
          date: '2026-09-23',
          y: '2026',
          m: '09',
          d: '23',
          weekday: '周三',
          courseLabel: '跑馬地',
          source: 'api',
          races: [
            Race(num: 1, name: '真', time: '18:40', meta: '', runners: const []),
          ],
        ),
      );
      final fallback = FallbackRaceRepository(
        demo: demo,
        api: counting,
        config: const JjjcApiConfig(),
      );
      final meeting = await fallback.load('2026-09-23');
      expect(meeting.raceByNum(1)!.runners, hasLength(12));
      expect(counting.calls, 0);
      expect(const JjjcApiConfig().isConfigured, isFalse);
      expect(
        const JjjcApiConfig(baseUrl: 'https://apicc.up.railway.app/')
            .resolvedBase,
        'https://apicc.up.railway.app',
      );
    },
  );
}
