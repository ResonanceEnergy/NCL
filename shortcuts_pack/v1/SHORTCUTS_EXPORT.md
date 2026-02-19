Exporting `.shortcut` packages (manual steps — macOS required)

Shortcuts .shortcut files can only be exported from the Shortcuts app on macOS/iOS. Below are copy-ready manual steps you can follow on a Mac that has the Shortcuts app.

Steps (macOS)
1. On your Mac, open the Shortcuts app.
2. Create a new Shortcut and add actions per the recipes in `shortcuts_pack/v1/recipes/`.
3. In the Text action, paste the QuickPaste snippet from `shortcuts_pack/v1/quickpaste/*.txt` and replace placeholders with Shortcuts variables.
4. Test the Shortcut by running it; verify the JSON file appears in iCloud Drive → `NCL/events/`.
5. When ready to export: File → Export → choose `Shortcut` (or right-click the shortcut → Export File...). Save the `.shortcut` package.
6. Share the `.shortcut` file or include it in a release/zip for distribution.

Notes & caveats
- iOS 17+ supports importing `.shortcut` files; confirm compatibility across OS versions.
- I cannot generate `.shortcut` binaries in this environment; follow the steps above on a mac.
- If you want, I can provide a ready-to-copy README or a release asset manifest for packaging the `.shortcut` files once you export them.
