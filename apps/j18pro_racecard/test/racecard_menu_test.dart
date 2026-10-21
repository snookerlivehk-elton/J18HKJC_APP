import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/text_scale_controller.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/racecard_table/row_chrome.dart';
import 'package:j18pro_racecard/features/racecard_table/swallowtail_flag.dart';
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

Future<void> _openMenu(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('menu-stub')));
  await tester.pumpAndSettle();
}

Future<void> _openCalendar(WidgetTester tester) async {
  await _openMenu(tester);
  await tester.tap(find.byKey(const Key('menu-race-date')));
  await tester.pumpAndSettle();
}

Future<void> _closeCalendar(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('cal-close')));
  await tester.pumpAndSettle();
}

Future<void> _dismissTopSheet(WidgetTester tester) async {
  await tester.tapAt(const Offset(12, 12));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('picking a race day switches the table to that meeting', (
    tester,
  ) async {
    await _pumpApp(tester);
    expect(find.text('跑馬地 · 2026-09-23'), findsOneWidget);
    expect(find.text('本領非凡'), findsOneWidget);

    await tester.tap(find.byKey(const Key('flag-5-1')));
    await tester.pump();

    await _openCalendar(tester);
    expect(find.text('2026年9月'), findsOneWidget);
    expect(find.byKey(const Key('cal-day-2026-09-02')), findsNothing);

    await tester.tap(find.byKey(const Key('cal-next')));
    await tester.pumpAndSettle();
    expect(find.text('2026年10月'), findsOneWidget);
    await tester.tap(find.byKey(const Key('cal-day-2026-10-01')));
    await tester.pump();
    await _closeCalendar(tester);

    expect(find.text('沙田 · 2026-10-01'), findsOneWidget);
    expect(find.textContaining('賽事資料載入中'), findsOneWidget);
    expect(find.byKey(const Key('empty-runners')), findsOneWidget);
    expect(find.text('暫無馬匹'), findsOneWidget);
    expect(find.text('本領非凡'), findsNothing);
    expect(find.byKey(const Key('race-pill-5')), findsNothing);

    await _openCalendar(tester);
    expect(find.text('2026年10月'), findsOneWidget);
    await tester.tap(find.byKey(const Key('cal-prev')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cal-day-2026-09-23')));
    await tester.pump();
    await _closeCalendar(tester);

    expect(find.text('跑馬地 · 2026-09-23'), findsOneWidget);
    expect(find.text('本領非凡'), findsOneWidget);
    expect(find.text('堅多福'), findsNothing);
    expect(find.byKey(const Key('race-pill-5')), findsOneWidget);
    expect(
      tester.widget<SwallowtailFlag>(find.byKey(const Key('flag-5-1'))).color,
      RowChrome.lightIdleFlag,
    );
  });

  testWidgets('overseas scope loads the overseas stub meeting', (tester) async {
    await _pumpApp(tester);
    await _openCalendar(tester);
    await tester.tap(find.byKey(const Key('cal-scope-os')));
    await tester.pumpAndSettle();
    expect(find.text('2026年9月'), findsOneWidget);
    expect(find.text('英國'), findsOneWidget);
    await tester.tap(find.byKey(const Key('cal-day-2026-09-27')));
    await tester.pump();
    await _closeCalendar(tester);

    expect(find.text('雅士谷 · 2026-09-27'), findsOneWidget);
    expect(find.textContaining('雅士谷'), findsWidgets);
    expect(find.byKey(const Key('empty-runners')), findsOneWidget);
    expect(find.text('本領非凡'), findsNothing);
  });

  testWidgets('famous and tip sheets follow the global date only', (
    tester,
  ) async {
    await _pumpApp(tester);
    await _openMenu(tester);
    await tester.tap(find.byKey(const Key('menu-famous')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('sheet-famous')), findsOneWidget);
    expect(find.text('跟隨賽日 2026-09-23'), findsOneWidget);
    expect(find.text('稍後提供'), findsOneWidget);
    expect(find.byKey(const Key('race-calendar')), findsNothing);
    expect(find.text('上一個月'), findsNothing);
    expect(find.text('香港馬'), findsNothing);
    await _dismissTopSheet(tester);

    await _openMenu(tester);
    await tester.tap(find.byKey(const Key('menu-tip-record')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sheet-tip-record')), findsOneWidget);
    expect(find.text('跟隨賽日 2026-09-23'), findsOneWidget);
    expect(find.byKey(const Key('race-calendar')), findsNothing);
    await _dismissTopSheet(tester);

    await _openMenu(tester);
    await tester.tap(find.byKey(const Key('menu-col-sort')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sheet-col-sort')), findsOneWidget);
    expect(find.text('馬匹數據排序'), findsOneWidget);
    expect(find.text('稍後提供'), findsOneWidget);
    await _dismissTopSheet(tester);

    await _openCalendar(tester);
    await tester.tap(find.byKey(const Key('cal-next')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cal-day-2026-10-01')));
    await tester.pump();
    await _closeCalendar(tester);

    await _openMenu(tester);
    await tester.tap(find.byKey(const Key('menu-famous')));
    await tester.pumpAndSettle();
    expect(find.text('跟隨賽日 2026-10-01'), findsOneWidget);
    expect(find.byKey(const Key('race-calendar')), findsNothing);

    await _dismissTopSheet(tester);
    await _openMenu(tester);
    await tester.tap(find.byKey(const Key('menu-tip-record')));
    await tester.pumpAndSettle();
    expect(find.text('跟隨賽日 2026-10-01'), findsOneWidget);
    expect(find.text('上一個月'), findsNothing);
  });

  testWidgets('menu theme and text scale apply to the main table', (
    tester,
  ) async {
    await _pumpApp(tester);
    expect(find.byType(Switch), findsOneWidget);

    await _openMenu(tester);
    expect(find.text('字體'), findsOneWidget);
    expect(find.byType(Switch), findsNWidgets(2));
    expect(
      tester.widget<IconButton>(find.byKey(const Key('zoom-out'))).onPressed,
      isNull,
    );

    await tester.tap(find.byKey(const Key('menu-theme')));
    await tester.pumpAndSettle();
    expect(find.text('選單'), findsOneWidget);
    expect(
      tester.widget<Switch>(find.byKey(const Key('menu-theme'))).value,
      isTrue,
    );
    expect(
      tester.widget<RowBand>(find.byKey(const Key('row-5-1'))).color,
      RowChrome.darkRow,
    );

    TextScaler scalerOf(String label) {
      return MediaQuery.textScalerOf(tester.element(find.text(label)));
    }

    expect(scalerOf('本領非凡').scale(1), textScaleFactor(0));
    expect(scalerOf('排位').scale(1), 1);

    await tester.tap(find.byKey(const Key('zoom-in')));
    await tester.pumpAndSettle();
    expect(find.text('選單'), findsOneWidget);
    expect(scalerOf('本領非凡').scale(1), textScaleFactor(1));
    expect(scalerOf('排位').scale(1), 1);

    await tester.tap(find.byKey(const Key('zoom-in')));
    await tester.pumpAndSettle();
    expect(scalerOf('本領非凡').scale(1), textScaleFactor(2));
    expect(scalerOf('排位').scale(1), 1);
    expect(
      tester.widget<IconButton>(find.byKey(const Key('zoom-in'))).onPressed,
      isNull,
    );

    await tester.tap(find.byKey(const Key('zoom-reset')));
    await tester.pumpAndSettle();
    expect(scalerOf('本領非凡').scale(1), textScaleFactor(0));
    expect(
      tester.widget<IconButton>(find.byKey(const Key('zoom-out'))).onPressed,
      isNull,
    );
  });
}
