import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';

/// Visible light/dark switch. Web hides this inside the menu; Phase 0
/// surfaces it on the top bar so the shell can be accepted on its own.
class ThemeToggle extends ConsumerWidget {
  const ThemeToggle({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isDark = ref.watch(themeModeProvider) == ThemeMode.dark;
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    return Tooltip(
      message: '切換深淺色主題',
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            '深色',
            style: TextStyle(
              color: Colors.white,
              fontSize: 13,
              fontWeight: FontWeight.w700,
              fontFamily: 'Noto Sans TC',
            ),
          ),
          Semantics(
            label: '深色',
            toggled: isDark,
            child: Switch(
              value: isDark,
              thumbColor: const WidgetStatePropertyAll(Colors.white),
              trackColor: WidgetStateProperty.resolveWith((states) {
                if (states.contains(WidgetState.selected)) return tokens.orange;
                return Colors.white24;
              }),
              trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
              onChanged: (value) {
                ref.read(themeModeProvider.notifier).setDark(value);
              },
            ),
          ),
        ],
      ),
    );
  }
}
