import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/features/col_sort/col_sort_sheet.dart';
import 'package:j18pro_racecard/features/famous_tips/famous_tips_sheet.dart';
import 'package:j18pro_racecard/features/app_menu/racecard_menu.dart';
import 'package:j18pro_racecard/features/board_sheet/board_sheet.dart';
import 'package:j18pro_racecard/features/horse_sheet/horse_sheet.dart';
import 'package:j18pro_racecard/features/jt_collab/jt_collab_sheet.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/racecard_insight/payout_sheet.dart';
import 'package:j18pro_racecard/features/race_calendar/race_calendar_sheet.dart';
import 'package:j18pro_racecard/features/synth_review/synth_review_sheet.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record_sheet.dart';
import 'package:j18pro_racecard/features/water_sheet/water_sheet.dart';

/// Shows at most one modal sheet. A new request replaces the current page.
class BoardSheetAnchor extends ConsumerStatefulWidget {
  const BoardSheetAnchor({super.key});

  @override
  ConsumerState<BoardSheetAnchor> createState() => _BoardSheetAnchorState();
}

class _BoardSheetAnchorState extends ConsumerState<BoardSheetAnchor> {
  var _visible = false;

  @override
  Widget build(BuildContext context) {
    ref.listen(boardSheetProvider, (previous, next) {
      if (next != null && !_visible) {
        _visible = true;
        showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => const BoardSheetHost(),
        ).whenComplete(() {
          _visible = false;
          if (ref.read(boardSheetProvider) != null) {
            ref.read(boardSheetProvider.notifier).close();
          }
        });
      } else if (next == null && _visible) {
        _visible = false;
        Navigator.of(context).pop();
      }
    });
    return const SizedBox.shrink();
  }
}

class BoardSheetHost extends ConsumerWidget {
  const BoardSheetHost({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final request = ref.watch(boardSheetProvider);
    if (request == null) return const SizedBox.shrink();
    return switch (request.kind) {
      BoardSheetKind.menu => const RacecardMenu(),
      BoardSheetKind.calendar => const RaceCalendarSheet(),
      BoardSheetKind.tipRecord => const TipRecordSheet(),
      BoardSheetKind.famous => const FamousTipsSheet(),
      BoardSheetKind.colSort => const ColSortSheet(),
      BoardSheetKind.payout => _PayoutHost(raceNum: request.raceNum!),
      BoardSheetKind.horse => HorseSheet(horseNo: request.horseNo!),
      BoardSheetKind.water => const WaterSheet(),
      BoardSheetKind.synthReview => SynthReviewSheet(
        key: ValueKey(request.horseNo),
        horseNo: request.horseNo!,
      ),
      BoardSheetKind.jtCollab => JtCollabSheet(
        key: ValueKey(request.horseNo),
        horseNo: request.horseNo!,
      ),
    };
  }
}

class _PayoutHost extends ConsumerWidget {
  const _PayoutHost({required this.raceNum});

  final int raceNum;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final meeting = ref.watch(racecardControllerProvider).asData?.value.meeting;
    final race = meeting?.raceByNum(raceNum);
    if (race == null) {
      return const SafeArea(
        child: Padding(
          padding: EdgeInsets.all(20),
          child: Text(
            '暫無派彩資料',
            style: TextStyle(fontFamily: 'Noto Sans TC', fontSize: 16),
          ),
        ),
      );
    }
    return PayoutDetailSheet(race: race);
  }
}
