import 'package:flutter/widgets.dart';
import 'package:j18pro_racecard/app/app_theme.dart';

const _silkPalette = <Color>[
  Color(0xFFE10600),
  Color(0xFF111111),
  Color(0xFF0057B8),
  Color(0xFFFFD100),
  Color(0xFF00A651),
  Color(0xFFE4007C),
  Color(0xFF00B5E2),
  Color(0xFF8A8D8F),
  Color(0xFFFF6A00),
  Color(0xFF6F2C91),
  Color(0xFFA8D08D),
  Color(0xFF7A1F2B),
  Color(0xFFFFFFFF),
  Color(0xFFC5A028),
];

Color silkColorFor(int horseNo) {
  final index = horseNo <= 0 ? 0 : (horseNo - 1) % _silkPalette.length;
  return _silkPalette[index];
}

/// Widget tests use a binding whose type name contains `Test`. Skip the CDN
/// there so the demo snapshot's silk URLs do not open sockets.
bool j18SilkNetworkAllowed() {
  return !WidgetsBinding.instance.runtimeType.toString().contains('Test');
}

/// Colour block when the silk URL is missing or the image fails.
class SilkMark extends StatelessWidget {
  const SilkMark({
    required this.horseNo,
    required this.tokens,
    this.url,
    this.scratched = false,
    this.image,
    this.allowNetwork,
    super.key,
  });

  final int horseNo;
  final J18Tokens tokens;
  final String? url;
  final bool scratched;

  /// Test hook. Production leaves this null and uses [NetworkImage].
  final ImageProvider? image;
  final bool? allowNetwork;

  @override
  Widget build(BuildContext context) {
    final fallback = _block();
    final provider = image;
    final src = url;
    final network = allowNetwork ?? j18SilkNetworkAllowed();
    if (provider == null && (src == null || src.isEmpty || !network)) {
      return fallback;
    }
    return SizedBox(
      key: const Key('silk-mark'),
      width: 36,
      height: 28,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(4),
        child: Image(
          image: provider ?? NetworkImage(src!),
          fit: BoxFit.cover,
          gaplessPlayback: true,
          errorBuilder: (_, _, _) => fallback,
          loadingBuilder: (context, child, progress) {
            if (progress == null) return child;
            return fallback;
          },
        ),
      ),
    );
  }

  Widget _block() {
    return Container(
      key: const Key('silk-fallback'),
      width: 36,
      height: 28,
      decoration: BoxDecoration(
        color: scratched ? tokens.muted : silkColorFor(horseNo),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: tokens.line),
      ),
    );
  }
}
