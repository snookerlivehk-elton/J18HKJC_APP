import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/data/jjjc_transport.dart';
import 'package:j18pro_racecard/data/race_repository.dart';
import 'package:j18pro_racecard/features/board_sheet/board_sheet.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

String _okBody() {
  return jsonEncode({
    'zh-hk': {
      'RaceMap': 'data:image/png;base64,$_png',
      'RaceInfoChi': {
        'Racecourse': '跑馬地',
        'Distance': '1200米',
        'RaceName': '測試賽',
        'Date': '2026/10/20',
      },
    },
  });
}

class _ScriptedTransport implements JjjcTransport {
  _ScriptedTransport(
    this._body, {
    this.throwOffline = false,
    this.hold = false,
  });

  final String _body;
  final bool throwOffline;
  final bool hold;
  var calls = 0;
  final pending = <Completer<JjjcHttpResult>>[];

  @override
  Future<JjjcHttpResult> get(Uri uri, {Map<String, String>? headers}) {
    calls += 1;
    if (throwOffline) {
      return Future<JjjcHttpResult>.error(RaceLoadException('未能連線，請檢查網絡'));
    }
    final result = JjjcHttpResult(statusCode: 200, body: _body);
    if (!hold) return Future<JjjcHttpResult>.value(result);
    final gate = Completer<JjjcHttpResult>();
    pending.add(gate);
    return gate.future;
  }
}

Future<void> _prepare(WidgetTester tester) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _pump(
  WidgetTester tester,
  SharedPreferences preferences,
  JjjcTransport transport,
) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(preferences),
        jjjcTransportProvider.overrideWithValue(transport),
      ],
      child: const J18App(),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _back(WidgetTester tester) async {
  await tester.binding.handlePopRoute();
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('open, close, and system back stay on the racecard', (
    tester,
  ) async {
    await _prepare(tester);
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final transport = _ScriptedTransport(_okBody(), hold: true);
    await _pump(tester, preferences, transport);

    expect(find.text('跑馬地 · 2026-09-23'), findsOneWidget);
    await tester.tap(find.byKey(const Key('open-speed-map')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('sheet-speed-map')), findsOneWidget);
    expect(find.text('速勢走位圖'), findsOneWidget);
    expect(find.text('第5場 · 載入走位圖…'), findsOneWidget);
    expect(find.text('正在載入全場跑位圖…'), findsOneWidget);
    expect(find.text('稍後提供'), findsNothing);
    expect(find.byKey(const Key('horse-sheet')), findsNothing);
    expect(find.byKey(const Key('sheet-famous')), findsNothing);
    expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
    expect(find.text('選單'), findsNothing);

    transport.pending.single.complete(
      JjjcHttpResult(statusCode: 200, body: _okBody()),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('speed-image')), findsOneWidget);
    expect(find.text('第5場 · 跑馬地 · 1200米 · 測試賽 · 2026/10/20'), findsOneWidget);
    expect(find.bySemanticsLabel('第5場速勢走位圖'), findsOneWidget);
    expect(transport.calls, 1);

    await tester.tap(find.byKey(const Key('speed-close')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sheet-speed-map')), findsNothing);
    expect(find.text('排位'), findsOneWidget);

    await tester.tap(find.byKey(const Key('menu-stub')));
    await tester.pumpAndSettle();
    await _back(tester);
    await tester.tap(find.byKey(const Key('open-speed-map')));
    await tester.pumpAndSettle();
    expect(find.text('選單'), findsNothing);
    expect(find.byKey(const Key('sheet-speed-map')), findsOneWidget);
    await _back(tester);
    expect(find.byKey(const Key('sheet-speed-map')), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.text('排位'), findsOneWidget);
    expect(transport.calls, 1);
  });

  testWidgets('an open menu is replaced by the speed map sheet', (
    tester,
  ) async {
    await _prepare(tester);
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final transport = _ScriptedTransport(_okBody());
    await _pump(tester, preferences, transport);

    await tester.tap(find.byKey(const Key('menu-stub')));
    await tester.pumpAndSettle();
    expect(find.text('選單'), findsOneWidget);

    final context = tester.element(find.text('選單'));
    ProviderScope.containerOf(context)
        .read(boardSheetProvider.notifier)
        .open(const BoardSheetRequest.speedMap(5));
    await tester.pumpAndSettle();

    expect(find.text('選單'), findsNothing);
    expect(find.byKey(const Key('sheet-speed-map')), findsOneWidget);
    expect(find.byKey(const Key('speed-image')), findsOneWidget);
  });

  testWidgets('a failed fetch stays inside the sheet and leaves the table', (
    tester,
  ) async {
    await _prepare(tester);
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final transport = _ScriptedTransport(_okBody(), throwOffline: true);
    await _pump(tester, preferences, transport);

    await tester.tap(find.byKey(const Key('open-speed-map')));
    await tester.pumpAndSettle();

    expect(find.text('暫未能載入走位圖，請稍後再試'), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('speed-meta'))).data,
      '第5場',
    );
    expect(find.text('本領非凡'), findsOneWidget);
    expect(find.text('排位'), findsOneWidget);
    expect(find.byKey(const Key('racecard-error')), findsNothing);

    await tester.tap(find.byKey(const Key('speed-close')));
    await tester.pumpAndSettle();
    expect(find.text('排位'), findsOneWidget);
    expect(find.text('本領非凡'), findsOneWidget);
  });

  testWidgets('json without a chart shows the empty placeholder', (
    tester,
  ) async {
    await _prepare(tester);
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final transport = _ScriptedTransport(
      jsonEncode({
        'zh-hk': {'RaceMap': '', 'RaceInfoChi': {}},
      }),
    );
    await _pump(tester, preferences, transport);

    await tester.tap(find.byKey(const Key('race-pill-6')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-speed-map')));
    await tester.pumpAndSettle();

    expect(find.text('此場暫無走位圖'), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('speed-meta'))).data,
      '第6場',
    );
    expect(find.text('雙劍合璧'), findsOneWidget);
    expect(find.byKey(const Key('racecard-error')), findsNothing);
  });
}
