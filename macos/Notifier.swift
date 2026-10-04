// Luckbox.app: posts the daily notification and, when it's clicked, opens the brief.
//   Luckbox.app/Contents/MacOS/Luckbox post "<title>" "<body>" "<url>"
// Clicking a delivered notification relaunches the app, which opens the URL and quits.
// Opening the app yourself (Spotlight, Dock, Finder) opens today's brief.
import Cocoa
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var handledClick = false

    func applicationWillFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().delegate = self
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let args = CommandLine.arguments
        guard args.count >= 5, args[1] == "post" else {
            // Launched by a notification click, the response arrives through the delegate within moments.
            // Launched by hand, none arrives: open the brief page.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                if !self.handledClick, let url = URL(string: "http://127.0.0.1:8765/") { NSWorkspace.shared.open(url) }
                NSApp.terminate(nil)
            }
            return
        }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else {
                FileHandle.standardError.write("notifications not allowed for Luckbox\n".data(using: .utf8)!)
                exit(2)
            }
            let content = UNMutableNotificationContent()
            content.title = args[2]
            content.body = args[3]
            content.userInfo = ["url": args[4]]
            content.sound = .default
            let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            center.add(request) { error in
                if let error = error { FileHandle.standardError.write("\(error)\n".data(using: .utf8)!) }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) { exit(error == nil ? 0 : 1) }
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        handledClick = true
        if let s = response.notification.request.content.userInfo["url"] as? String, let url = URL(string: s) {
            NSWorkspace.shared.open(url)
        }
        done()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
