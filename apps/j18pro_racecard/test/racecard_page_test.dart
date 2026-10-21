import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/app/j18_app.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/racecard/racecard_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<SharedPreferences> _pumpApp(
  WidgetTester tester, {
  Map<String, Object> initial = const {},
}) async {
  SharedPreferences.setMockInitialValues(initial);
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
  return preferences;
}

void main() {
  testWidgets('shows 排位 and toggles light to dark', (tester) async {
    tester.view.physicalSize = const Size(430, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final preferences = await _pumpApp(tester);

    expect(find.text('排位'), findsOneWidget);
    expect(find.byType(RacecardPage), findsOneWidget);
    expect(find.byType(Switch), findsOneWidget);
    expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);

    final lightContext = tester.element(find.text('排位'));
    expect(Theme.of(lightContext).brightness, Brightness.light);
    expect(
      Theme.of(lightContext).extension<J18Tokens>()!.nav,
      const Color(0xFF3D5A80),
    );
    expect(
      Theme.of(lightContext).extension<J18Tokens>()!.green,
      const Color(0xFF5CB85C),
    );
    expect(
      Theme.of(lightContext).extension<J18Tokens>()!.orange,
      const Color(0xFFE88B2A),
    );

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();

    expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);
    final darkContext = tester.element(find.text('排位'));
    expect(Theme.of(darkContext).brightness, Brightness.dark);
    expect(
      Theme.of(darkContext).extension<J18Tokens>()!.nav,
      const Color(0xFF6A86A8),
    );
    expect(
      Theme.of(darkContext).extension<J18Tokens>()!.orange,
      const Color(0xFFE39A45),
    );
    expect(preferences.getString(themePreferenceKey), 'dark');

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
    expect(preferences.getString(themePreferenceKey), 'light');
  });

  testWidgets('restores dark theme from j18-racecard-theme', (tester) async {
    await _pumpApp(tester, initial: {themePreferenceKey: 'dark'});

    expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);
    expect(
      Theme.of(tester.element(find.byType(RacecardPage))).brightness,
      Brightness.dark,
    );
  });
}
