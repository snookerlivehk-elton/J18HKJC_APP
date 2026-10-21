import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/data/jjjc_transport.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/features/speed_map/speed_map.dart';
import 'package:j18pro_racecard/features/speed_map/speed_map_repository.dart';

/// 1×1 PNG.
const _png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

String _payload({
  String? zhMap,
  String? enMap,
  bool includeZh = true,
  Map<String, Object?>? zhInfo,
}) {
  final body = <String, Object?>{};
  if (includeZh) {
    body['zh-hk'] = {
      'RaceMap': ?zhMap,
      'RaceInfoChi':
          zhInfo ??
          {
            'Racecourse': '跑馬地',
            'Distance': 1200,
            'RaceName': '測試賽',
            'Date': '2026/10/20',
          },
      'RaceInfoEng': {'Racecourse': 'Happy Valley'},
    };
  }
  body['en-us'] = {
    'RaceMap': ?enMap,
    'RaceInfoEng': {
      'Racecourse': 'Sha Tin',
      'Distance': '1400',
      'RaceName': 'EN',
      'Date': '2026/10/20',
    },
  };
  return jsonEncode(body);
}

class _FakeTransport implements JjjcTransport {
  _FakeTransport(this._handler);

  final JjjcHttpResult Function(Uri uri) _handler;
  final uris = <Uri>[];

  @override
  Future<JjjcHttpResult> get(Uri uri, {Map<String, String>? headers}) async {
    uris.add(uri);
    return _handler(uri);
  }
}

void main() {
  test('zh-hk wins, BOM is stripped, and meta follows the web order', () {
    final raw =
        '\uFEFF${_payload(zhMap: 'data:image/png;base64,$_png', enMap: 'data:image/png;base64,$_png')}';
    final chart = parseSpeedMap(raw);
    expect(chart.course, '跑馬地');
    expect(chart.distance, '1200');
    expect(chart.raceName, '測試賽');
    expect(chart.metaFor(5), '第5場 · 跑馬地 · 1200 · 測試賽 · 2026/10/20');
    expect(chart.bytes, base64Decode(_png));
  });

  test('en-us is used only when zh-hk is absent', () {
    final chart = parseSpeedMap(
      _payload(includeZh: false, enMap: 'data:image/png;base64,$_png'),
    );
    expect(chart.course, 'Sha Tin');
    expect(chart.metaFor(1), '第1場 · Sha Tin · 1400 · EN · 2026/10/20');
  });

  test('an empty zh-hk map is no chart and does not fall through', () {
    expect(
      () => parseSpeedMap(
        _payload(zhMap: '', enMap: 'data:image/png;base64,$_png'),
      ),
      throwsA(
        isA<SpeedMapException>().having(
          (error) => error.kind,
          'kind',
          SpeedMapFailure.noChart,
        ),
      ),
    );
    expect(
      () => parseSpeedMap('{"zh-hk":{"RaceMap":"https://example/x.png"}}'),
      throwsA(
        isA<SpeedMapException>().having(
          (error) => error.kind,
          'kind',
          SpeedMapFailure.noChart,
        ),
      ),
    );
  });

  test('cache hit skips the network until the ten minute TTL', () async {
    var now = DateTime(2026, 10, 21, 12);
    final transport = _FakeTransport(
      (uri) => JjjcHttpResult(
        statusCode: 200,
        body: _payload(zhMap: 'data:image/png;base64,$_png'),
      ),
    );
    final repo = SpeedMapRepository(
      transport: transport,
      cache: SpeedMapCache(clock: () => now),
    );

    final first = await repo.load(5);
    final second = await repo.load(5);
    expect(identical(first, second), isTrue);
    expect(transport.uris, [speedMapUri(5)]);

    now = now.add(const Duration(minutes: 10));
    await repo.load(5);
    expect(transport.uris, [speedMapUri(5), speedMapUri(5)]);
  });

  test('offline and no-chart results are not cached', () async {
    var status = 500;
    var body = 'nope';
    final transport = _FakeTransport(
      (uri) => JjjcHttpResult(statusCode: status, body: body),
    );
    final repo = SpeedMapRepository(
      transport: transport,
      cache: SpeedMapCache(),
    );

    await expectLater(
      repo.load(1),
      throwsA(
        isA<SpeedMapException>().having(
          (error) => error.kind,
          'kind',
          SpeedMapFailure.offline,
        ),
      ),
    );
    status = 200;
    body = _payload(zhMap: '');
    await expectLater(
      repo.load(1),
      throwsA(
        isA<SpeedMapException>().having(
          (error) => error.kind,
          'kind',
          SpeedMapFailure.noChart,
        ),
      ),
    );
    body = '{';
    await expectLater(
      repo.load(1),
      throwsA(
        isA<SpeedMapException>().having(
          (error) => error.kind,
          'kind',
          SpeedMapFailure.offline,
        ),
      ),
    );
    expect(transport.uris, hasLength(3));

    final throwing = SpeedMapRepository(
      transport: _ThrowingTransport(),
      cache: SpeedMapCache(),
    );
    await expectLater(
      throwing.load(2),
      throwsA(
        isA<SpeedMapException>().having(
          (error) => error.kind,
          'kind',
          SpeedMapFailure.offline,
        ),
      ),
    );
  });
}

class _ThrowingTransport implements JjjcTransport {
  @override
  Future<JjjcHttpResult> get(Uri uri, {Map<String, String>? headers}) async {
    throw RaceLoadException('未能連線，請檢查網絡');
  }
}
