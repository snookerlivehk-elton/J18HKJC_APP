import 'package:flutter/material.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/payout_detail.dart';

/// Web payout detail sheet. Only opened when [raceHasPayout] is true.
class PayoutDetailSheet extends StatelessWidget {
  const PayoutDetailSheet({required this.race, super.key});

  final Race race;

  @override
  Widget build(BuildContext context) {
    final sections = buildPayoutDetailSections(race);
    final height = MediaQuery.sizeOf(context).height * 0.72;
    return SafeArea(
      child: SizedBox(
        key: const Key('payout-detail-sheet'),
        height: height,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                '派彩',
                style: const TextStyle(
                  fontFamily: 'Noto Sans TC',
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '第${race.num}場 ${race.name}',
                style: const TextStyle(
                  fontFamily: 'Noto Sans TC',
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: sections.isEmpty
                    ? const Align(
                        alignment: Alignment.topLeft,
                        child: Text(
                          '暫無派彩資料',
                          style: TextStyle(
                            fontFamily: 'Noto Sans TC',
                            fontSize: 15,
                          ),
                        ),
                      )
                    : SingleChildScrollView(
                        child: Table(
                          columnWidths: const {
                            0: FlexColumnWidth(1.1),
                            1: FlexColumnWidth(1.4),
                            2: FlexColumnWidth(1.2),
                          },
                          defaultVerticalAlignment:
                              TableCellVerticalAlignment.middle,
                          children: [
                            const TableRow(
                              children: [
                                _HeadCell('彩池'),
                                _HeadCell('勝出組合'),
                                _HeadCell('派彩'),
                              ],
                            ),
                            for (final section in sections)
                              for (var i = 0; i < section.rows.length; i++)
                                TableRow(
                                  children: [
                                    _BodyCell(i == 0 ? section.pool : ''),
                                    _BodyCell(section.rows[i].combo),
                                    _BodyCell(
                                      fmtPayoutAmt(section.rows[i].pay),
                                    ),
                                  ],
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

class _HeadCell extends StatelessWidget {
  const _HeadCell(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 13,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _BodyCell extends StatelessWidget {
  const _BodyCell(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Text(
        text,
        style: const TextStyle(fontFamily: 'Noto Sans TC', fontSize: 13),
      ),
    );
  }
}
