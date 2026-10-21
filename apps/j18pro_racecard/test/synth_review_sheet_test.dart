import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _prepareView(WidgetTester tester) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _pumpApp(
  WidgetTester tester,
  SharedPreferences preferences,
) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [sharedPreferencesProvider.overrideWithValue(preferences)],
      child: const J18App(),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _systemBack(WidgetTester tester) async {
  await tester.binding.handlePopRoute();
  await tester.pumpAndSettle();
}

Future<void> _openSynth(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('horse-open-1')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('open-synth-review')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'synth review replaces the horse sheet and excludes other sheets',
    (tester) async {
      await _prepareView(tester);
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      await _pumpApp(tester, preferences);
      await _openSynth(tester);

      expect(find.byKey(const Key('sheet-synth-review')), findsOneWidget);
      expect(find.text('綜合評述 · 1 本領非凡'), findsOneWidget);
      expect(find.textContaining('模型勝率達22.56%'), findsOneWidget);
      expect(find.text('稍後提供'), findsNothing);
      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.byKey(const Key('sheet-famous')), findsNothing);
      expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
      expect(find.byKey(const Key('race-calendar')), findsNothing);
      expect(find.text('選單'), findsNothing);

      await tester.tap(find.byKey(const Key('synth-close')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('sheet-synth-review')), findsNothing);
      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.text('排位'), findsOneWidget);
    },
  );

  testWidgets(
    'system back closes the review and does not restore the horse sheet',
    (tester) async {
      await _prepareView(tester);
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      await _pumpApp(tester, preferences);
      await tester.tap(find.byKey(const Key('menu-stub')));
      await tester.pumpAndSettle();
      expect(find.text('選單'), findsOneWidget);

      await _systemBack(tester);
      await _openSynth(tester);
      await tester.enterText(
        find.byKey(const Key('synth-note-input')),
        '返回亦保存',
      );
      await _systemBack(tester);

      expect(find.byKey(const Key('sheet-synth-review')), findsNothing);
      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.text('選單'), findsNothing);
      expect(find.text('排位'), findsOneWidget);

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();
      await _pumpApp(tester, preferences);
      await _openSynth(tester);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('synth-note-input')))
            .controller
            ?.text,
        '返回亦保存',
      );
    },
  );

  testWidgets('a saved note is still there after the app is built again', (
    tester,
  ) async {
    await _prepareView(tester);
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    await _pumpApp(tester, preferences);
    await _openSynth(tester);

    await tester.enterText(find.byKey(const Key('synth-note-input')), '後期追前');
    await tester.ensureVisible(find.byKey(const Key('synth-note-save')));
    await tester.tap(find.byKey(const Key('synth-note-save')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('synth-note-hist')));
    await tester.tap(find.byKey(const Key('synth-note-hist')));
    await tester.pumpAndSettle();

    expect(find.textContaining('（1條）'), findsOneWidget);
    final row = find.byWidgetPredicate((widget) {
      final key = widget.key;
      return key is ValueKey<String> && key.value.startsWith('synth-hist-');
    });
    expect(row, findsOneWidget);
    await tester.tap(row);
    await tester.pump();
    expect(find.text('後期追前'), findsOneWidget);

    await tester.tap(find.byKey(const Key('synth-close')));
    await tester.pumpAndSettle();

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await _pumpApp(tester, preferences);
    await _openSynth(tester);

    expect(
      tester
          .widget<TextField>(find.byKey(const Key('synth-note-input')))
          .controller
          ?.text,
      '後期追前',
    );
    expect(find.textContaining('（1條）'), findsOneWidget);
  });
}
