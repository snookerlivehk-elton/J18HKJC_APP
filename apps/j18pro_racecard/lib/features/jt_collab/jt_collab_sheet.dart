import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/jt_collab/jt_collab.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record_sheet.dart';

/// Web `jtCollabOverlay`. One board sheet; opening it replaces any other.
class JtCollabSheet extends ConsumerWidget {
  const JtCollabSheet({required this.horseNo, super.key});

  final int horseNo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final view = ref.watch(racecardControllerProvider).asData?.value;
    final race = view?.currentRace;
    Runner? runner;
    if (race != null) {
      for (final item in race.runners) {
        if (item.no == horseNo) {
          runner = item;
          break;
        }
      }
    }
    final demo = jtCollabDemo(
      horseNo: horseNo,
      raceNum: race?.num ?? 0,
      jockeyRaw: runner?.jockey,
      trainerRaw: runner?.trainer,
    );
    final horse = runner?.name ?? '';
    final title = runner == null
        ? '騎練合作'
        : '騎練合作 · $horseNo${horse.isEmpty ? '' : ' $horse'}';
    final maxHeight = MediaQuery.sizeOf(context).height * 0.9;
    return TipSheetScroll(
      key: const Key('sheet-jt-collab'),
      maxHeight: maxHeight,
      header: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 4, 0),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  key: const Key('jt-title'),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: tokens.text,
                  ),
                ),
              ),
              Semantics(
                button: true,
                label: '關閉',
                child: ExcludeSemantics(
                  child: IconButton(
                    key: const Key('jt-close'),
                    tooltip: '關閉',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: demo.hasPeople
              ? _Body(demo: demo, tokens: tokens)
              : Text(
                  '暫無騎練資料',
                  key: const Key('jt-empty'),
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 14,
                    color: tokens.muted,
                  ),
                ),
        ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.demo, required this.tokens});

  final JtCollabDemo demo;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          demo.pair,
          key: const Key('jt-pair'),
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: tokens.text,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          demo.summary,
          key: const Key('jt-summary'),
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 13,
            height: 1.4,
            color: tokens.muted,
          ),
        ),
        const SizedBox(height: 10),
        if (demo.races.isEmpty)
          Text(
            '暫無歷史合作戰績',
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 14,
              color: tokens.muted,
            ),
          )
        else
          for (var i = 0; i < demo.races.length; i++)
            _RaceRow(index: i, race: demo.races[i], tokens: tokens),
      ],
    );
  }
}

class _RaceRow extends StatelessWidget {
  const _RaceRow({
    required this.index,
    required this.race,
    required this.tokens,
  });

  final int index;
  final JtCollabRace race;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: Key('jt-row-$index'),
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  race.date,
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 14,
                    color: tokens.text,
                  ),
                ),
                Text(
                  '${race.course} · ${race.dist}',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 12,
                    color: tokens.muted,
                  ),
                ),
              ],
            ),
          ),
          Text(
            race.finishLabel,
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: tokens.text,
            ),
          ),
        ],
      ),
    );
  }
}
