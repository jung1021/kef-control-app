# winget (Windows Package Manager)

Once these manifests are merged into [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs), anyone can install KEF Control with:

```powershell
winget install jung1021.KEFControl      # or: winget install kef-control
```

## Submitting a release (after the GitHub release with the .exe is published)

Easiest, on Windows, with Microsoft's helper:
```powershell
winget install wingetcreate
wingetcreate submit --token <a GitHub token with public_repo scope> packaging\winget\manifests\j\jung1021\KEFControl\1.3.0
```
`wingetcreate` forks winget-pkgs, adds the files and opens the pull request. Microsoft's bots validate the installer, which takes a day or two.

For later versions:
```powershell
wingetcreate update jung1021.KEFControl --version 1.4.0 --urls https://github.com/jung1021/kef-control-app/releases/download/v1.4.0/KEFControl-Setup-1.4.0.exe --submit
```

> The `InstallerSha256` must match the file attached to the release exactly. If the installer is rebuilt, update the hash (`Get-FileHash .\KEFControl-Setup-1.3.0.exe`).
