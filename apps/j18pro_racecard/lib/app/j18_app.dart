import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/app/router.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';

/// Root widget. Product locale is zh-HK; state lives in Riverpod only.
class J18App extends ConsumerWidget {
  const J18App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeMode = ref.watch(themeModeProvider);
    return MaterialApp(
      title: '排位',
      debugShowCheckedModeBanner: false,
      locale: const Locale('zh', 'HK'),
      supportedLocales: const [Locale('zh', 'HK')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: J18Theme.light(),
      darkTheme: J18Theme.dark(),
      themeMode: themeMode,
      initialRoute: J18Routes.racecard,
      routes: J18Routes.builders,
    );
  }
}
