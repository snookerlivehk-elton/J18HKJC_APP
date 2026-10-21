import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';

/// Phase 5 sheet placeholder. The date is the global meeting date only.
class PlaceholderSheet extends ConsumerWidget {
  const PlaceholderSheet({
    required this.title,
    required this.sheetKey,
    super.key,
  });

  final String title;
  final Key sheetKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final date = ref
        .watch(racecardControllerProvider)
        .asData
        ?.value
        .meeting
        .date;
    return SafeArea(
      child: Padding(
        key: sheetKey,
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 18,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '跟隨賽日 ${date ?? '—'}',
              key: const Key('global-date-label'),
              style: const TextStyle(fontFamily: 'Noto Sans TC', fontSize: 15),
            ),
            const SizedBox(height: 8),
            const Text(
              '稍後提供',
              style: TextStyle(fontFamily: 'Noto Sans TC', fontSize: 15),
            ),
          ],
        ),
      ),
    );
  }
}
