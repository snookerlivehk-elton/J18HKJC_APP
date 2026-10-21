import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/racecard/runner_odds_row.dart';
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
      overrides: [
        sharedPreferencesProvider.overrideWithValue(preferences),
      ],
      child: const J18App(),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('switching races updates the list and marks scratched horses', (tester) async {
    await _pumpApp(tester);

    expect(find.text('本領非凡'), findsOneWidget);
    expect(find.text('堅多福'), findsNothing);
    expect(find.text('已退出'), findsNothing);
    expect(find.text('跑馬地 · 2026-09-23'), findsOneWidget);

    await tester.tap(find.byKey(const Key('race-selector')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('第1場 南風讓賽').last);
    await tester.pumpAndSettle();

    expect(find.text('堅多福'), findsOneWidget);
    expect(find.text('本領非凡'), findsNothing);
    final race1 = tester.widget<RunnerOddsRow>(
      find.widgetWithText(RunnerOddsRow, '堅多福'),
    );
    expect(race1.runner.scratched, isFalse);
    expect(race1.runner.win, 13);
    expect(race1.runner.place, 4);
    expect(find.text('13'), findsWidgets);
    expect(find.text('4'), findsWidgets);

    await tester.tap(find.byKey(const Key('race-selector')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('第6場 香島讓賽').last);
    await tester.pumpAndSettle();

    expect(find.text('本領非凡'), findsNothing);
    expect(find.text('雙劍合璧'), findsOneWidget);
    expect(find.text('已退出'), findsOneWidget);
    final scratched = tester.widget<RunnerOddsRow>(
      find.widgetWithText(RunnerOddsRow, '雙劍合璧'),
    );
    expect(scratched.runner.scratched, isTrue);
    expect(scratched.runner.win, isNull);
    final name = tester.widget<Text>(find.text('雙劍合璧'));
    expect(name.style?.decoration, TextDecoration.lineThrough);
  });
}
