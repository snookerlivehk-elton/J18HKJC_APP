import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record_sheet.dart';
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

Future<void> _openTip(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('menu-stub')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('menu-tip-record')));
  await tester.pumpAndSettle();
}

Future<void> _systemBack(WidgetTester tester) async {
  await tester.binding.handlePopRoute();
  await tester.pumpAndSettle();
}

Finder _sheetScrollable() {
  return find.descendant(
    of: find.byKey(const Key('sheet-tip-record')),
    matching: find.byType(Scrollable),
  );
}

void main() {
  testWidgets('tip sheet scrolls when tall and shrinks when short', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Align(
            alignment: Alignment.bottomCenter,
            child: TipSheetScroll(maxHeight: 400, child: Text('短')),
          ),
        ),
      ),
    );
    final short = tester.renderObject<RenderBox>(find.byType(TipSheetScroll));
    expect(short.size.height, lessThan(80));
    expect(
      tester
          .state<ScrollableState>(find.byType(Scrollable))
          .position
          .maxScrollExtent,
      0,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Align(
            alignment: Alignment.bottomCenter,
            child: TipSheetScroll(
              maxHeight: 400,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (var i = 0; i < 40; i++)
                    const SizedBox(height: 30, child: Text('行')),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    final tall = tester.renderObject<RenderBox>(find.byType(TipSheetScroll));
    expect(tall.size.height, 400);
    expect(
      tester
          .state<ScrollableState>(find.byType(Scrollable))
          .position
          .maxScrollExtent,
      greaterThan(0),
    );
  });

  testWidgets('menu opens tip record and keeps a single sheet', (tester) async {
    await _pumpApp(tester);
    await _openTip(tester);

    expect(find.byKey(const Key('sheet-tip-record')), findsOneWidget);
    expect(find.text('心水戰績 · 23/9'), findsOneWidget);
    expect(find.text('今日心水'), findsOneWidget);
    expect(find.text('戰績統計'), findsOneWidget);
    expect(find.text('心水名家榜 · 獎金 Top 10'), findsOneWidget);
    expect(find.text('谷草快手'), findsOneWidget);
    expect(find.text(r'$18,640'), findsOneWidget);
    expect(find.text('個人心水和戰績'), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.text('稍後提供'), findsNothing);
    expect(find.byKey(const Key('race-calendar')), findsNothing);
    expect(find.byKey(const Key('horse-sheet')), findsNothing);
    expect(find.byKey(const Key('water-sheet')), findsNothing);
    expect(find.byKey(const Key('sheet-famous')), findsNothing);
    expect(find.byKey(const Key('sheet-col-sort')), findsNothing);
    expect(find.text('上一個月'), findsNothing);

    final race1 = find.byKey(const Key('tip-day-race-1'));
    final circles = tester.widgetList<NumberCircle>(
      find.descendant(of: race1, matching: find.byType(NumberCircle)),
    );
    expect(circles.map((circle) => circle.text).toList(), [
      '11',
      '8',
      '3',
      '4',
      '6',
      '1',
    ]);
    expect(circles.first.kind, CircleKind.win);
    expect(circles.elementAt(3).kind, CircleKind.fourth);
    expect(circles.last.kind, CircleKind.plain);

    final race5 = find.byKey(const Key('tip-day-race-5'));
    expect(
      tester
          .widget<NumberCircle>(
            find
                .descendant(of: race5, matching: find.byType(NumberCircle))
                .first,
          )
          .kind,
      CircleKind.plain,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('tip-day-race-6')),
        matching: find.text('7'),
      ),
      findsNothing,
    );

    expect(find.text('前2個號碼'), findsNothing);
    await tester.tap(find.byKey(const Key('tip-help')));
    await tester.pumpAndSettle();
    expect(find.textContaining('前2個號碼'), findsOneWidget);
    expect(find.textContaining('每注 10 元'), findsOneWidget);

    expect(
      tester.widget<Text>(find.byKey(const Key('tip-stat-rate-top3'))).data,
      '100.0%',
    );
    expect(find.textContaining(r'$1,762'), findsOneWidget);
    await tester.tap(find.byKey(const Key('tip-scope-season')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<Text>(find.byKey(const Key('tip-stat-rate-top3'))).data,
      '71.4%',
    );
    expect(find.textContaining(r'$10,002'), findsOneWidget);

    expect(find.byKey(const Key('tip-lb-detail-u1')), findsNothing);
    await tester.scrollUntilVisible(
      find.byKey(const Key('tip-lb-u1')),
      300,
      scrollable: _sheetScrollable(),
    );
    await tester.tap(find.byKey(const Key('tip-lb-u1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('tip-lb-detail-u1')), findsOneWidget);
    expect(find.text('42.9%'), findsOneWidget);
    expect(find.text('18/42場'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.byKey(const Key('tip-lb-u2')),
      200,
      scrollable: _sheetScrollable(),
    );
    await tester.tap(find.byKey(const Key('tip-lb-u2')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('tip-lb-detail-u1')), findsOneWidget);
    expect(find.byKey(const Key('tip-lb-detail-u2')), findsOneWidget);

    expect(
      tester
          .state<ScrollableState>(_sheetScrollable())
          .position
          .maxScrollExtent,
      greaterThan(0),
    );

    await tester.tap(find.byKey(const Key('tip-close')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.text('排位'), findsOneWidget);

    await _openTip(tester);
    expect(find.byKey(const Key('tip-lb-detail-u1')), findsNothing);
    expect(find.byKey(const Key('tip-help-body')), findsNothing);
    await _systemBack(tester);
    expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.byKey(const Key('horse-sheet')), findsNothing);
  });
}
