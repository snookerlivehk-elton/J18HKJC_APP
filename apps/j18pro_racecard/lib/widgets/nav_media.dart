import 'package:flutter/material.dart';

/// Web `navLiveTv` / `navRadio` reserved slots.
///
/// There is no stream in this app. The buttons stay disabled and say
/// 稍後提供, so a tap cannot start playback or blank the racecard.
class NavMediaPlaceholders extends StatelessWidget {
  const NavMediaPlaceholders({super.key});

  @override
  Widget build(BuildContext context) {
    return const Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _MediaButton(
          buttonKey: Key('nav-live-tv'),
          label: '現場直播，稍後提供',
          icon: Icons.live_tv,
        ),
        _MediaButton(
          buttonKey: Key('nav-radio'),
          label: '收音機，稍後提供',
          icon: Icons.radio,
        ),
      ],
    );
  }
}

class _MediaButton extends StatelessWidget {
  const _MediaButton({
    required this.buttonKey,
    required this.label,
    required this.icon,
  });

  final Key buttonKey;
  final String label;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      enabled: false,
      label: label,
      child: ExcludeSemantics(
        child: IconButton(
          key: buttonKey,
          tooltip: label,
          onPressed: null,
          visualDensity: VisualDensity.compact,
          padding: EdgeInsets.zero,
          constraints: const BoxConstraints.tightFor(width: 36, height: 36),
          style: IconButton.styleFrom(disabledForegroundColor: Colors.white70),
          icon: Icon(icon, size: 20),
        ),
      ),
    );
  }
}
