#include "events.hpp"
#import <Foundation/Foundation.h>
#import <UserNotifications/UserNotifications.h>

@interface UmekoNotificationDelegate : NSObject<UNUserNotificationCenterDelegate>
@end
@implementation UmekoNotificationDelegate
- (void)userNotificationCenter:(UNUserNotificationCenter *)center
      willPresentNotification:(UNNotification *)notification
        withCompletionHandler:(void (^)(UNNotificationPresentationOptions))completion {
  completion(UNNotificationPresentationOptionBanner | UNNotificationPresentationOptionList | UNNotificationPresentationOptionSound);
}
- (void)userNotificationCenter:(UNUserNotificationCenter *)center
 didReceiveNotificationResponse:(UNNotificationResponse *)response
        withCompletionHandler:(void (^)(void))completion {
  const auto id = std::string(response.notification.request.identifier.UTF8String);
  const bool dismissed = [response.actionIdentifier isEqualToString:UNNotificationDismissActionIdentifier];
  notifyEvent(dismissed ? "dismissed" : "clicked", id);
  [center removeDeliveredNotificationsWithIdentifiers:@[response.notification.request.identifier]];
  completion();
}
@end
static UmekoNotificationDelegate *delegate;
static UNUserNotificationCenter *center;
int umeko_notify_init(const char *, const char *, const char *) {
  @autoreleasepool {
    // UNUserNotificationCenter raises an exception for unbundled test/CLI executables.
    if (NSBundle.mainBundle.bundleIdentifier.length == 0 || ![NSBundle.mainBundle.bundleURL.pathExtension isEqualToString:@"app"]) return 0;
    center = UNUserNotificationCenter.currentNotificationCenter;
    delegate = [UmekoNotificationDelegate new]; center.delegate = delegate;
    UNNotificationCategory *category = [UNNotificationCategory categoryWithIdentifier:@"umeko.task" actions:@[] intentIdentifiers:@[] options:UNNotificationCategoryOptionCustomDismissAction];
    [center setNotificationCategories:[NSSet setWithObject:category]];
    return 1;
  }
}
int umeko_notify_show(const char *identifier, const char *title, const char *body) {
  @autoreleasepool {
    if (!center) return 0;
    NSString *key = [NSString stringWithUTF8String:identifier];
    UNMutableNotificationContent *content = [UNMutableNotificationContent new];
    content.title = [NSString stringWithUTF8String:title]; content.body = [NSString stringWithUTF8String:body];
    content.sound = UNNotificationSound.defaultSound; content.categoryIdentifier = @"umeko.task"; content.threadIdentifier = @"umeko.tasks";
    void (^deliver)(void) = ^{
      UNNotificationRequest *request = [UNNotificationRequest requestWithIdentifier:key content:content trigger:nil];
      [center addNotificationRequest:request withCompletionHandler:^(NSError *error) {
        if (error) notifyEvent("failed", key.UTF8String);
      }];
    };
    [center getNotificationSettingsWithCompletionHandler:^(UNNotificationSettings *settings) {
      if (settings.authorizationStatus == UNAuthorizationStatusNotDetermined) {
        [center requestAuthorizationWithOptions:(UNAuthorizationOptionAlert | UNAuthorizationOptionSound) completionHandler:^(BOOL granted, NSError *error) {
          if (granted && !error) deliver(); else notifyEvent("denied", key.UTF8String);
        }];
      } else if (settings.authorizationStatus == UNAuthorizationStatusAuthorized || settings.authorizationStatus == UNAuthorizationStatusProvisional) deliver();
      else notifyEvent("denied", key.UTF8String);
    }];
    return 1;
  }
}
