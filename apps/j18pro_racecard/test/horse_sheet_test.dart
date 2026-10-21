import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/water_sheet/water_sheet.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _pumpApp(WidgetTester tester) async {
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

Future<void> _systemBack(WidgetTester tester) async {
  await tester.binding.handlePopRoute();
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('horse sheet opens from the name and closes with back', (
    tester,
  ) async {
    await _pumpApp(tester);
    await tester.tap(find.byKey(const Key('horse-open-1')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('horse-sheet')), findsOneWidget);
    expect(find.text('本領非凡'), findsWidgets);
    expect(find.text('第5場 香港鄉村俱樂部挑戰盃（讓賽）'), findsOneWidget);
    expect(find.text('檔位'), findsWidgets);
    expect(find.text('9'), findsWidgets);
    expect(find.byKey(const Key('horse-win')), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('horse-win'))).data, '12');
    expect(
      tester.widget<Text>(find.byKey(const Key('horse-place'))).data,
      '4.2',
    );
    expect(find.text('何澤堯'), findsWidgets);
    expect(find.text('Sacred Falls'), findsOneWidget);
    expect(find.text('30（2-5-1）'), findsOneWidget);

    await tester.tap(find.byKey(const Key('horse-close')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('horse-sheet')), findsNothing);
    expect(find.text('排位'), findsOneWidget);

    await tester.tap(find.byKey(const Key('horse-open-1')));
    await tester.pumpAndSettle();
    await _systemBack(tester);
    expect(find.byKey(const Key('horse-sheet')), findsNothing);
    expect(find.byKey(const Key('water-sheet')), findsNothing);
  });

  testWidgets('scratched horse sheet shows a dash instead of odds', (
    tester,
  ) async {
    await _pumpApp(tester);
    await tester.tap(find.byKey(const Key('race-pill-6')));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('horse-open-7')));
    await tester.tap(find.byKey(const Key('horse-open-7')));
    await tester.pumpAndSettle();

    expect(find.textContaining('已退出'), findsWidgets);
    expect(tester.widget<Text>(find.byKey(const Key('horse-win'))).data, '—');
    expect(tester.widget<Text>(find.byKey(const Key('horse-place'))).data, '—');
  });

  testWidgets(
    'water sheet replaces the horse sheet and back does not restore it',
    (tester) async {
      await _pumpApp(tester);
      await tester.tap(find.byKey(const Key('race-pill-1')));
      await tester.pump();
      await tester.ensureVisible(find.byKey(const Key('horse-open-9')));
      await tester.tap(find.byKey(const Key('horse-open-9')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-water')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.byKey(const Key('water-sheet')), findsOneWidget);
      expect(find.text('水位'), findsWidgets);
      expect(find.text('18:00'), findsOneWidget);
      expect(find.textContaining('上獨贏'), findsOneWidget);

      final cell = find.byKey(const Key('water-cell-9-0'));
      expect(cell, findsOneWidget);
      expect(
        find.descendant(of: cell, matching: find.text('86')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: cell, matching: find.text('10')),
        findsOneWidget,
      );
      expect(find.descendant(of: cell, matching: find.text('↙')), findsWidgets);

      await tester.tap(cell);
      await tester.pump();
      final selected = tester.widget<WaterHourCell>(cell);
      expect(selected.selected, isTrue);
      await tester.tap(cell);
      await tester.pump();
      expect(tester.widget<WaterHourCell>(cell).selected, isFalse);

      await _systemBack(tester);
      expect(find.byKey(const Key('water-sheet')), findsNothing);
      expect(find.byKey(const Key('horse-sheet')), findsNothing);
      expect(find.text('排位'), findsOneWidget);
    },
  );

  testWidgets('opening famous replaces the menu so back returns to the table', (
    tester,
  ) async {
    await _pumpApp(tester);
    await tester.tap(find.byKey(const Key('menu-stub')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('menu-famous')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sheet-famous')), findsOneWidget);
    expect(find.text('查看賽期和歷史數據'), findsNothing);

    await _systemBack(tester);
    expect(find.byKey(const Key('sheet-famous')), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.text('排位'), findsOneWidget);
  });
}
