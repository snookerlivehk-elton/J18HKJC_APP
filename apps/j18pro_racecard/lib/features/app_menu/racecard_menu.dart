import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/text_scale_controller.dart';
import 'package:j18pro_racecard/app/theme_mode_controller.dart';
import 'package:j18pro_racecard/features/board_sheet/board_sheet.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

/// Page menu. Theme and text scale stay open; the other entries replace it.
class RacecardMenu extends ConsumerWidget {
  const RacecardMenu({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final meeting = ref.watch(racecardControllerProvider).asData?.value.meeting;
    final isDark = ref.watch(themeModeProvider) == ThemeMode.dark;
    final level = ref.watch(textScaleLevelProvider);
    return SafeArea(
      child: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 0, 8, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(12, 0, 12, 4),
                child: Text(
                  '選單',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              ListTile(
                key: const Key('menu-race-date'),
                title: Text(
                  formatMenuDate(meeting?.date),
                  style: const TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontWeight: FontWeight.w700,
                  ),
                ),
                subtitle: const Text(
                  '查看賽期和歷史數據',
                  style: TextStyle(fontFamily: 'Noto Sans TC'),
                ),
                onTap: () => ref
                    .read(boardSheetProvider.notifier)
                    .open(const BoardSheetRequest.calendar()),
              ),
              ListTile(
                key: const Key('menu-tip-record'),
                title: const Text(
                  '個人心水和戰績',
                  style: TextStyle(fontFamily: 'Noto Sans TC'),
                ),
                onTap: () => ref
                    .read(boardSheetProvider.notifier)
                    .open(const BoardSheetRequest.tipRecord()),
              ),
              ListTile(
                key: const Key('menu-famous'),
                title: const Text(
                  '名家',
                  style: TextStyle(fontFamily: 'Noto Sans TC'),
                ),
                onTap: () => ref
                    .read(boardSheetProvider.notifier)
                    .open(const BoardSheetRequest.famous()),
              ),
              ListTile(
                key: const Key('menu-col-sort'),
                title: const Text(
                  '馬匹數據排序',
                  style: TextStyle(fontFamily: 'Noto Sans TC'),
                ),
                onTap: () => ref
                    .read(boardSheetProvider.notifier)
                    .open(const BoardSheetRequest.colSort()),
              ),
              const Divider(),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Row(
                  children: [
                    const Text(
                      '淺色',
                      style: TextStyle(
                        fontFamily: 'Noto Sans TC',
                        fontSize: 14,
                      ),
                    ),
                    Switch(
                      key: const Key('menu-theme'),
                      value: isDark,
                      onChanged: (value) {
                        ref.read(themeModeProvider.notifier).setDark(value);
                      },
                    ),
                    const Text(
                      '深色',
                      style: TextStyle(
                        fontFamily: 'Noto Sans TC',
                        fontSize: 14,
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 0),
                child: Semantics(
                  container: true,
                  explicitChildNodes: true,
                  label: '字號，第${level + 1}級，共${textScaleMaxLevel + 1}級',
                  child: Row(
                    children: [
                      const SizedBox(width: 8),
                      const Text(
                        '字體',
                        style: TextStyle(
                          fontFamily: 'Noto Sans TC',
                          fontSize: 14,
                        ),
                      ),
                      Semantics(
                        button: true,
                        enabled: level > 0,
                        label: '縮小',
                        child: ExcludeSemantics(
                          child: IconButton(
                            key: const Key('zoom-out'),
                            tooltip: '縮小',
                            onPressed: level <= 0
                                ? null
                                : () => ref
                                      .read(textScaleLevelProvider.notifier)
                                      .step(-1),
                            icon: const Icon(Icons.remove),
                          ),
                        ),
                      ),
                      Semantics(
                        button: true,
                        enabled: level < textScaleMaxLevel,
                        label: '放大',
                        child: ExcludeSemantics(
                          child: IconButton(
                            key: const Key('zoom-in'),
                            tooltip: '放大',
                            onPressed: level >= textScaleMaxLevel
                                ? null
                                : () => ref
                                      .read(textScaleLevelProvider.notifier)
                                      .step(1),
                            icon: const Icon(Icons.add),
                          ),
                        ),
                      ),
                      TextButton(
                        key: const Key('zoom-reset'),
                        onPressed: level == 0
                            ? null
                            : () => ref
                                  .read(textScaleLevelProvider.notifier)
                                  .reset(),
                        child: const Text(
                          '復原',
                          style: TextStyle(fontFamily: 'Noto Sans TC'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
