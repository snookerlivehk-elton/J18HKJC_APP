import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
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

Future<void> _openFamous(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('menu-stub')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('menu-famous')));
  await tester.pumpAndSettle();
}

Future<void> _systemBack(WidgetTester tester) async {
  await tester.binding.handlePopRoute();
  await tester.pumpAndSettle();
}

List<String> _circleTexts(WidgetTester tester, Finder scope) {
  return tester
      .widgetList<NumberCircle>(
        find.descendant(of: scope, matching: find.byType(NumberCircle)),
      )
      .map((circle) => circle.text)
      .toList();
}

void main() {
  testWidgets('menu opens famous tips without stacking another sheet', (
    tester,
  ) async {
    await _pumpApp(tester);
    final metaBefore = tester
        .widget<Text>(find.byKey(const Key('race-meta')))
        .data;
    await _openFamous(tester);

    expect(find.byKey(const Key('sheet-famous')), findsOneWidget);
    expect(find.text('名家貼士 · 23/9'), findsOneWidget);
    expect(find.text('綜合心水'), findsOneWidget);
    expect(find.text('臨場'), findsOneWidget);
    expect(find.text('早餐'), findsOneWidget);
    expect(find.text('馬房貼士'), findsOneWidget);
    expect(find.text('臨場神算'), findsOneWidget);
    expect(find.text('45.2%'), findsOneWidget);
    expect(find.text('（28/62場）'), findsOneWidget);
    expect(find.text('開跑前臨場提供'), findsOneWidget);
    expect(find.text('賽前一日或當日早上'), findsOneWidget);
    expect(find.text('練馬師團隊提供'), findsOneWidget);
    expect(find.text('尚未派彩'), findsOneWidget);
    expect(find.text('心水名家榜 · 獎金 Top 10'), findsNothing);
    expect(find.text('谷草快手'), findsNothing);
    expect(find.text('稍後提供'), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
    expect(find.byKey(const Key('sheet-col-sort')), findsNothing);
    expect(find.byKey(const Key('race-calendar')), findsNothing);
    expect(find.byKey(const Key('horse-sheet')), findsNothing);
    expect(find.text('上一個月'), findsNothing);

    expect(_circleTexts(tester, find.byKey(const Key('famous-agg'))), [
      '2',
      '10',
      '5',
      '1',
      '3',
      '9',
    ]);
    expect(
      tester
          .widget<NumberCircle>(
            find
                .descendant(
                  of: find.byKey(const Key('famous-agg')),
                  matching: find.byType(NumberCircle),
                )
                .first,
          )
          .kind,
      CircleKind.plain,
    );
    expect(_circleTexts(tester, find.byKey(const Key('famous-tipster-fl1'))), [
      '6',
      '3',
      '4',
      '1',
    ]);

    await tester.tap(find.byKey(const Key('famous-race-1')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<Text>(find.byKey(const Key('race-meta'))).data,
      metaBefore,
    );
    expect(find.text('冠亞季殿'), findsOneWidget);
    expect(find.text('尚未派彩'), findsNothing);
    final finish = tester.widgetList<NumberCircle>(
      find.descendant(
        of: find.byKey(const Key('famous-finish')),
        matching: find.byType(NumberCircle),
      ),
    );
    expect(finish.map((circle) => circle.text).toList(), ['11', '8', '3', '4']);
    expect(finish.map((circle) => circle.kind).toList(), [
      CircleKind.win,
      CircleKind.quinella,
      CircleKind.place,
      CircleKind.fourth,
    ]);
    expect(_circleTexts(tester, find.byKey(const Key('famous-agg'))), [
      '9',
      '12',
      '7',
      '5',
      '8',
      '2',
    ]);

    await tester.tap(find.byKey(const Key('famous-race-6')));
    await tester.pumpAndSettle();
    expect(
      find.descendant(
        of: find.byKey(const Key('famous-agg')),
        matching: find.text('7'),
      ),
      findsNothing,
    );
    expect(
      tester.widget<Text>(find.byKey(const Key('race-meta'))).data,
      metaBefore,
    );

    final vertical = find.descendant(
      of: find.byKey(const Key('sheet-famous')),
      matching: find.byWidgetPredicate(
        (widget) =>
            widget is Scrollable && widget.axisDirection == AxisDirection.down,
      ),
    );
    expect(
      tester.state<ScrollableState>(vertical).position.maxScrollExtent,
      greaterThan(0),
    );

    await tester.tap(find.byKey(const Key('famous-close')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sheet-famous')), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.text('排位'), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('race-meta'))).data,
      metaBefore,
    );

    await _openFamous(tester);
    expect(find.text('尚未派彩'), findsOneWidget);
    await _systemBack(tester);
    expect(find.byKey(const Key('sheet-famous')), findsNothing);
    expect(find.text('選單'), findsNothing);
    expect(find.byKey(const Key('sheet-tip-record')), findsNothing);
  });
}
