import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/col_sort/col_layout.dart';
import 'package:j18pro_racecard/features/qin/qin_panel.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _prepare(WidgetTester tester) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _pump(WidgetTester tester, SharedPreferences preferences) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [sharedPreferencesProvider.overrideWithValue(preferences)],
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
  testWidgets(
    'jt sheet replaces the horse sheet and back returns to the table',
    (tester) async {
      await _prepare(tester);
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      await _pump(tester, preferences);

      await tester.tap(find.byKey(const Key('horse-open-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-jt-collab')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('sheet-jt-collab')), findsOneWidget);
      expect(find.text('騎練合作 · 1 本領非凡'), findsOneWidget);
      expect(find.text('何澤堯 × 羅富全'), findsOneWidget);
      expect(find.textContaining('近季合作：'), findsOneWidget);
      expect(find.text('第5名'), findsWidgets);
      expect(find.text('稍後提供'), findsNothing);
      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.byKey(const Key('sheet-famous')), findsNothing);
      expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
      expect(find.text('選單'), findsNothing);

      await tester.tap(find.byKey(const Key('jt-close')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('sheet-jt-collab')), findsNothing);
      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.text('排位'), findsOneWidget);

      await tester.tap(find.byKey(const Key('menu-stub')));
      await tester.pumpAndSettle();
      await _back(tester);
      await tester.tap(find.byKey(const Key('horse-open-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-jt-collab')));
      await tester.pumpAndSettle();
      await _back(tester);
      expect(find.byKey(const Key('sheet-jt-collab')), findsNothing);
      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.text('選單'), findsNothing);
      expect(find.text('排位'), findsOneWidget);
    },
  );

  testWidgets('jockey cell opens the sheet and a scratched horse does not', (
    tester,
  ) async {
    await _prepare(tester);
    SharedPreferences.setMockInitialValues({
      colLayoutPreferenceKey: jsonEncode({
        'v': ['jockey'],
        'h': [
          'draw',
          'win',
          'place',
          'form6',
          'hw',
          'trainer',
          'age',
          'rating',
          'career',
          'gear',
          'dam',
          'sire',
          'damsire',
          'owner',
          'prize',
        ],
      }),
    });
    final preferences = await SharedPreferences.getInstance();
    await _pump(tester, preferences);

    expect(find.byKey(const Key('jt-open-jockey-1')), findsOneWidget);
    await tester.tap(find.byKey(const Key('jt-open-jockey-1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sheet-jt-collab')), findsOneWidget);
    expect(find.text('選單'), findsNothing);
    await tester.tap(find.byKey(const Key('jt-close')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('race-pill-6')));
    await tester.pump();
    expect(find.byKey(const Key('jt-open-jockey-7')), findsNothing);
  });

  testWidgets('qin panel toggles a pair and switches to place odds', (
    tester,
  ) async {
    await _prepare(tester);
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    await _pump(tester, preferences);

    final panel = find.byKey(const Key('qin-panel'));
    await tester.ensureVisible(panel);
    await tester.pumpAndSettle();
    expect(find.textContaining('連贏賠率'), findsOneWidget);
    expect(find.text('暫無連贏組合'), findsNothing);

    final hot = find.byWidgetPredicate((widget) {
      return widget is QinMatrixCell && widget.hot;
    });
    expect(hot, findsOneWidget);
    final before = tester.widget<QinMatrixCell>(hot).text;
    await tester.tap(hot);
    await tester.pump();
    expect(tester.widget<QinMatrixCell>(hot).focused, isTrue);
    final index = find.byWidgetPredicate((widget) {
      final key = widget.key;
      return widget is QinMatrixCell &&
          key is ValueKey<String> &&
          key.value.startsWith('qin-idx-');
    });
    expect(
      tester.widgetList<QinMatrixCell>(index).any((cell) => cell.focused),
      isTrue,
    );

    await tester.ensureVisible(find.byKey(const Key('qin-mode-qpl')));
    await tester.tap(find.byKey(const Key('qin-mode-qpl')));
    await tester.pump();
    expect(find.textContaining('連贏位置賠率'), findsOneWidget);
    expect(tester.widget<QinMatrixCell>(hot).text, isNot(before));
  });
}
