import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('app version is 1.x and is not the web 0.2 line', () {
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final match = RegExp(
      r'^version:\s*(\S+)\s*$',
      multiLine: true,
    ).firstMatch(pubspec);
    expect(match, isNotNull);
    final version = match!.group(1)!;
    expect(version, '1.0.0+1');
    expect(version.startsWith('0.2'), isFalse);
  });

  test('release manifest has internet and no unused sensitive permissions', () {
    final manifest = File('android/app/src/main/AndroidManifest.xml')
        .readAsStringSync();
    expect(manifest, contains('android.permission.INTERNET'));
    for (final unused in [
      'CAMERA',
      'RECORD_AUDIO',
      'ACCESS_FINE_LOCATION',
      'ACCESS_COARSE_LOCATION',
      'READ_EXTERNAL_STORAGE',
      'READ_MEDIA_IMAGES',
      'POST_NOTIFICATIONS',
      'FOREGROUND_SERVICE',
      'RECEIVE_BOOT_COMPLETED',
    ]) {
      expect(manifest, isNot(contains(unused)));
    }
    final gradle = File('android/app/build.gradle.kts').readAsStringSync();
    expect(gradle, contains('applicationId = "hk.j18.j18pro_racecard"'));
    expect(gradle, contains('J18_UPLOAD_STORE_FILE'));
    expect(gradle, isNot(contains('storePassword = "')));
  });

  test('ios privacy manifest declares user defaults and not tracking', () {
    final privacy = File('ios/Runner/PrivacyInfo.xcprivacy').readAsStringSync();
    expect(privacy, contains('NSPrivacyTracking'));
    expect(privacy, contains('<false/>'));
    expect(privacy, contains('NSPrivacyAccessedAPICategoryUserDefaults'));
    expect(privacy, contains('CA92.1'));
    final project = File('ios/Runner.xcodeproj/project.pbxproj')
        .readAsStringSync();
    expect(project, contains('PrivacyInfo.xcprivacy in Resources'));

    final plist = File('ios/Runner/Info.plist').readAsStringSync();
    expect(plist, contains('ITSAppUsesNonExemptEncryption'));
    expect(plist, contains('FLUTTER_BUILD_NAME'));
    expect(plist, contains('FLUTTER_BUILD_NUMBER'));
    for (final unused in [
      'NSPhotoLibraryUsageDescription',
      'NSCameraUsageDescription',
      'NSLocationWhenInUseUsageDescription',
      'NSMicrophoneUsageDescription',
      'NSAllowsArbitraryLoads',
    ]) {
      expect(plist, isNot(contains(unused)));
    }
  });

  test('store docs exist and do not claim an upload happened', () {
    final release = File('docs/STORE_RELEASE.md').readAsStringSync();
    final review = File('docs/STORE_REVIEW_DRAFT.md').readAsStringSync();
    expect(release, contains('1.0.0+1'));
    expect(release, contains('需人工'));
    expect(release, contains('**没有**执行上传'));
    expect(review, contains('example.invalid'));
    expect(review, contains('需人工'));
    expect(review, contains('没有上传'));
    expect(review, contains('賽馬排位，只供參考'));
    expect(review, contains('Racecard. Information only.'));
    expect(review.toLowerCase(), isNot(contains('uploaded to testflight')));
  });
}
