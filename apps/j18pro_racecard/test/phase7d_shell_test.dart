import 'dart:ui' show Tristate;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [sharedPreferencesProvider.overrideWithValue(preferences)],
      child: const J18App(),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('live and radio placeholders stay disabled and leave the table', (
    tester,
  ) async {
    await _pump(tester);

    expect(find.byKey(const Key('nav-live-tv')), findsOneWidget);
    expect(find.byKey(const Key('nav-radio')), findsOneWidget);
    expect(
      tester.widget<IconButton>(find.byKey(const Key('nav-live-tv'))).onPressed,
      isNull,
    );
    expect(
      tester.widget<IconButton>(find.byKey(const Key('nav-radio'))).onPressed,
      isNull,
    );
    expect(find.bySemanticsLabel('現場直播，稍後提供'), findsOneWidget);
    expect(find.bySemanticsLabel('收音機，稍後提供'), findsOneWidget);
    expect(find.bySemanticsLabel('選單'), findsOneWidget);
    expect(find.text('排位'), findsOneWidget);
    expect(find.text('本領非凡'), findsOneWidget);
    expect(find.byKey(const Key('racecard-error')), findsNothing);

    await tester.tap(find.byKey(const Key('race-pill-6')));
    await tester.pumpAndSettle();
    expect(find.text('雙劍合璧'), findsOneWidget);
    expect(find.byKey(const Key('nav-live-tv')), findsOneWidget);
    expect(find.text('排位'), findsOneWidget);
  });

  testWidgets(
    'race pills, horse open, text scale, and sheet close are labeled',
    (tester) async {
      await _pump(tester);

      final current = find.bySemanticsLabel(RegExp(r'^第5場$'));
      expect(current, findsOneWidget);
      expect(
        tester.getSemantics(current).flagsCollection.isSelected,
        Tristate.isTrue,
      );
      expect(find.bySemanticsLabel('開啟第1號 本領非凡'), findsOneWidget);

      await tester.tap(find.byKey(const Key('horse-open-1')));
      await tester.pumpAndSettle();
      expect(find.byTooltip('關閉'), findsOneWidget);
      expect(find.bySemanticsLabel('關閉'), findsOneWidget);
      await tester.tap(find.byKey(const Key('horse-close')));
      await tester.pumpAndSettle();
      expect(find.text('排位'), findsOneWidget);

      await tester.tap(find.byKey(const Key('menu-stub')));
      await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('字號，第1級，共3級'), findsOneWidget);
      expect(find.byTooltip('縮小'), findsOneWidget);
      expect(find.byTooltip('放大'), findsOneWidget);
    },
  );
}
