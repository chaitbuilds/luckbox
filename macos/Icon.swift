// Draws the luckbox icon (a four-leaf clover on a rounded square) to a 1024px PNG.
//   swift macos/Icon.swift out.png
import AppKit

let size: CGFloat = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let paper = NSColor(srgbRed: 0.965, green: 0.953, blue: 0.925, alpha: 1)
let leaf = NSColor(srgbRed: 0.18, green: 0.42, blue: 0.30, alpha: 1)

// macOS-style rounded square with a margin
let inset: CGFloat = 100
paper.setFill()
NSBezierPath(roundedRect: NSRect(x: inset, y: inset, width: size - 2 * inset, height: size - 2 * inset),
             xRadius: 185, yRadius: 185).fill()

// Four heart-shaped leaves: each is two overlapping circles pointing at the center
let c = NSPoint(x: size / 2, y: size / 2 + 30)
let r: CGFloat = 92
leaf.setFill()
for k in 0..<4 {
    let a = CGFloat(k) * .pi / 2 + .pi / 4
    let dir = NSPoint(x: cos(a), y: sin(a))
    let side = NSPoint(x: -dir.y, y: dir.x)
    for s in [-1.0, 1.0] as [CGFloat] {
        let p = NSPoint(x: c.x + dir.x * 128 + side.x * s * 58, y: c.y + dir.y * 128 + side.y * s * 58)
        NSBezierPath(ovalIn: NSRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)).fill()
    }
    let tip = NSBezierPath()
    tip.move(to: c)
    tip.line(to: NSPoint(x: c.x + dir.x * 128 + side.x * 140, y: c.y + dir.y * 128 + side.y * 140))
    tip.line(to: NSPoint(x: c.x + dir.x * 128 - side.x * 140, y: c.y + dir.y * 128 - side.y * 140))
    tip.close(); tip.fill()
}
// Thin paper-colored cross splits the shape into four distinct heart-shaped leaves
paper.setStroke()
for (from, to) in [(NSPoint(x: c.x, y: c.y - 300), NSPoint(x: c.x, y: c.y + 300)),
                   (NSPoint(x: c.x - 300, y: c.y), NSPoint(x: c.x + 300, y: c.y))] {
    let gap = NSBezierPath(); gap.move(to: from); gap.line(to: to); gap.lineWidth = 26; gap.stroke()
}
// Stem
let stem = NSBezierPath()
stem.move(to: NSPoint(x: c.x, y: c.y - 20))
stem.curve(to: NSPoint(x: c.x + 70, y: 220), controlPoint1: NSPoint(x: c.x + 10, y: 330), controlPoint2: NSPoint(x: c.x + 40, y: 260))
stem.lineWidth = 34; stem.lineCapStyle = .round; leaf.setStroke(); stem.stroke()

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
