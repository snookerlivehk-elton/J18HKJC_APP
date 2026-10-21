import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Same key as Web `localStorage["j18-racecard-theme"]`.
/// Values are `light` or `dark`. Missing key means light, matching Web.
const themePreferenceKey = 'j18-racecard-theme';

/// Overridden in `main` (and tests) after [SharedPreferences.getInstance].
final sharedPreferencesProvider = Provider<SharedPreferences>((ref) {
  throw StateError('sharedPreferencesProvider must be overridden');
});

/// Project-wide state container. Do not introduce Bloc alongside this.
final themeModeProvider = NotifierProvider<ThemeModeController, ThemeMode>(
  ThemeModeController.new,
);

class ThemeModeController extends Notifier<ThemeMode> {
  @override
  ThemeMode build() {
    final stored = ref.watch(sharedPreferencesProvider).getString(themePreferenceKey);
    return stored == 'dark' ? ThemeMode.dark : ThemeMode.light;
  }

  Future<void> setDark(bool isDark) async {
    final next = isDark ? ThemeMode.dark : ThemeMode.light;
    if (state == next) return;
    state = next;
    await ref
        .read(sharedPreferencesProvider)
        .setString(themePreferenceKey, isDark ? 'dark' : 'light');
  }
}
