import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/racecard_table/row_chrome.dart';
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
  testWidgets('switching races updates the table and marks scratched horses', (tester) async {
    await _pumpApp(tester);

    expect(find.text('本領非凡'), findsOneWidget);
    expect(find.text('堅多福'), findsNothing);
    expect(find.text('已退出'), findsNothing);
    expect(find.text('跑馬地 · 2026-09-23'), findsOneWidget);
    expect(find.byType(RowBand), findsNWidgets(11));
    expect(find.text('載入賽事'), findsNothing);

    await tester.tap(find.byKey(const Key('race-pill-1')));
    await tester.pump();

    expect(find.text('載入賽事'), findsNothing);
    expect(find.text('堅多福'), findsOneWidget);
    expect(find.text('本領非凡'), findsNothing);
    expect(find.byType(RowBand), findsNWidgets(12));
    expect(find.text('13'), findsWidgets);
    expect(find.text('4'), findsWidgets);

    await tester.tap(find.byKey(const Key('race-pill-6')));
    await tester.pump();

    expect(find.text('本領非凡'), findsNothing);
    expect(find.text('堅多福'), findsNothing);
    expect(find.text('雙劍合璧'), findsOneWidget);
    expect(find.text('已退出'), findsOneWidget);
    expect(find.text('37'), findsNothing);
    expect(find.byType(RowBand), findsNWidgets(10));
    final name = tester.widget<Text>(find.text('雙劍合璧'));
    expect(name.style?.decoration, TextDecoration.lineThrough);
    final scratched = tester.widget<RowBand>(find.byKey(const Key('row-6-7')));
    expect(scratched.color, RowChrome.lightRow);
  });
}
