import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/col_sort/col_layout.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<SharedPreferences> _pumpApp(WidgetTester tester) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  await _mount(tester, preferences);
  return preferences;
}

Future<void> _mount(WidgetTester tester, SharedPreferences preferences) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [sharedPreferencesProvider.overrideWithValue(preferences)],
      child: const J18App(),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _openColSort(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('menu-stub')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('menu-col-sort')));
  await tester.pumpAndSettle();
}

Future<void> _closeSheet(WidgetTester tester) async {
  await tester.ensureVisible(find.byKey(const Key('col-sort-close')));
  await tester.tap(find.byKey(const Key('col-sort-close')));
  await tester.pumpAndSettle();
}

Future<void> _systemBack(WidgetTester tester) async {
  await tester.binding.handlePopRoute();
  await tester.pumpAndSettle();
}

double _headerDx(WidgetTester tester, String label) {
  return tester
      .getTopLeft(
        find.descendant(
          of: find.byKey(const Key('scroll-header')),
          matching: find.text(label),
        ),
      )
      .dx;
}

void main() {
  testWidgets('show hide and reorder rewrite the main table', (tester) async {
    await _pumpApp(tester);
    await _openColSort(tester);

    expect(find.byKey(const Key('sheet-col-sort')), findsOneWidget);
    expect(find.text('馬匹數據排序'), findsOneWidget);
    expect(find.text('未顯示'), findsOneWidget);
    expect(find.text('已顯示'), findsOneWidget);
    expect(find.text('復位'), findsOneWidget);
    expect(find.text('稍後提供'), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.byKey(const Key('race-calendar')), findsNothing);
    expect(find.byKey(const Key('sheet-famous')), findsNothing);
    expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
    expect(find.byKey(const Key('horse-sheet')), findsNothing);
    expect(find.byKey(const Key('col-vis-draw')), findsOneWidget);
    expect(find.byKey(const Key('col-vis-win')), findsOneWidget);
    expect(find.byKey(const Key('col-vis-place')), findsOneWidget);
    expect(find.byKey(const Key('col-vis-form6')), findsOneWidget);
    expect(find.byKey(const Key('col-hid-jockey')), findsOneWidget);
    expect(
      tester.widget<IconButton>(find.byKey(const Key('col-sort-up'))).onPressed,
      isNull,
    );
    expect(
      tester
          .widget<IconButton>(find.byKey(const Key('col-sort-down')))
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<IconButton>(find.byKey(const Key('col-sort-left')))
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<IconButton>(find.byKey(const Key('col-sort-right')))
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<IconButton>(find.byKey(const Key('col-sort-close')))
          .tooltip,
      '關閉',
    );

    await tester.tap(find.byKey(const Key('col-vis-form6')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<IconButton>(find.byKey(const Key('col-sort-up'))).onPressed,
      isNotNull,
    );
    expect(
      tester
          .widget<IconButton>(find.byKey(const Key('col-sort-down')))
          .onPressed,
      isNull,
    );
    await tester.tap(find.byKey(const Key('col-sort-up')));
    await tester.pumpAndSettle();
    await _closeSheet(tester);

    expect(_headerDx(tester, '檔位'), lessThan(_headerDx(tester, '獨贏')));
    expect(_headerDx(tester, '獨贏'), lessThan(_headerDx(tester, '近績')));
    expect(_headerDx(tester, '近績'), lessThan(_headerDx(tester, '位置')));

    await _openColSort(tester);
    await tester.tap(find.byKey(const Key('col-vis-win')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('col-sort-left')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('col-hid-win')), findsOneWidget);
    await _closeSheet(tester);
    expect(find.text('獨贏'), findsNothing);
    expect(find.text('近績'), findsOneWidget);

    await _openColSort(tester);
    await tester.ensureVisible(find.byKey(const Key('col-sort-reset')));
    await tester.tap(find.byKey(const Key('col-sort-reset')));
    await tester.pumpAndSettle();
    await _closeSheet(tester);
    expect(find.text('獨贏'), findsOneWidget);
    expect(_headerDx(tester, '位置'), lessThan(_headerDx(tester, '近績')));

    await _openColSort(tester);
    await tester.ensureVisible(find.byKey(const Key('col-hid-jockey')));
    await tester.tap(find.byKey(const Key('col-hid-jockey')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('col-sort-right')));
    await tester.tap(find.byKey(const Key('col-sort-right')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('col-vis-jockey')), findsOneWidget);
    await _closeSheet(tester);
    expect(find.text('騎師'), findsOneWidget);
    expect(find.text('何澤堯'), findsWidgets);

    await _openColSort(tester);
    expect(find.text('選單'), findsNothing);
    await _systemBack(tester);
    expect(find.text('排位'), findsOneWidget);
    expect(find.text('選單'), findsNothing);
    expect(find.byKey(const Key('sheet-col-sort')), findsNothing);
    expect(find.text('馬匹數據排序'), findsNothing);
  });

  testWidgets('column layout survives a new app with the same preferences', (
    tester,
  ) async {
    final preferences = await _pumpApp(tester);
    await _openColSort(tester);
    await tester.tap(find.byKey(const Key('col-vis-win')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('col-sort-left')));
    await tester.pumpAndSettle();
    await _closeSheet(tester);
    expect(find.text('獨贏'), findsNothing);
    expect(preferences.getString(colLayoutPreferenceKey), isNotNull);

    await _mount(tester, preferences);
    expect(find.text('獨贏'), findsNothing);
    expect(find.text('檔位'), findsOneWidget);
    expect(find.text('近績'), findsOneWidget);
  });

  testWidgets('an empty visible list leaves the table without those headers', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(430, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var layout = defaultColLayout;
    for (final id in [...layout.visible]) {
      layout = colMoveToHidden(layout, id);
    }
    SharedPreferences.setMockInitialValues({
      colLayoutPreferenceKey: encodeColLayout(layout),
    });
    final preferences = await SharedPreferences.getInstance();
    await _mount(tester, preferences);

    expect(find.text('檔位'), findsNothing);
    expect(find.text('獨贏'), findsNothing);
    expect(find.text('位置'), findsNothing);
    expect(find.text('近績'), findsNothing);
    expect(find.text('本領非凡'), findsOneWidget);

    await _openColSort(tester);
    expect(find.byKey(const Key('col-empty-vis')), findsOneWidget);
    expect(find.text('（空）'), findsOneWidget);
    expect(find.byKey(const Key('col-hid-draw')), findsOneWidget);
  });
}
