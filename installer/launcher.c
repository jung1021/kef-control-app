/* KEFControl.exe - starts the bundled Python runtime with the app script.
   Layout:  KEFControl.exe, runtime\pythonw.exe, app\kef_control.py */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

static const wchar_t *skip_argv0(const wchar_t *cl) {
    if (*cl == L'"') { cl++; while (*cl && *cl != L'"') cl++; if (*cl) cl++; }
    else { while (*cl && *cl != L' ' && *cl != L'\t') cl++; }
    while (*cl == L' ' || *cl == L'\t') cl++;
    return cl;
}

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, LPWSTR cmd, int show) {
    wchar_t exe[MAX_PATH * 2], dir[MAX_PATH * 2], py[MAX_PATH * 2], script[MAX_PATH * 2];
    DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH * 2);
    if (!n || n >= MAX_PATH * 2) return 1;
    wcscpy(dir, exe);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    _snwprintf(py, MAX_PATH * 2, L"%ls\\runtime\\pythonw.exe", dir);
    _snwprintf(script, MAX_PATH * 2, L"%ls\\app\\kef_control.py", dir);
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"KEF Control's runtime files are missing. Please reinstall KEF Control.",
                    L"KEF Control", MB_ICONERROR);
        return 2;
    }
    SetEnvironmentVariableW(L"KEFCONTROL_EXE", exe);
    SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", NULL);

    const wchar_t *args = skip_argv0(GetCommandLineW());
    size_t len = wcslen(py) + wcslen(script) + wcslen(args) + 16;
    wchar_t *line = (wchar_t *)HeapAlloc(GetProcessHeap(), 0, len * sizeof(wchar_t));
    if (!line) return 3;
    _snwprintf(line, len, L"\"%ls\" \"%ls\" %ls", py, script, args);

    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si); si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(py, line, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Couldn't start KEF Control.", L"KEF Control", MB_ICONERROR);
        return 4;
    }
    /* --quit must finish before the installer continues, so wait for it. */
    if (wcsstr(args, L"--quit")) WaitForSingleObject(pi.hProcess, 20000);
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}
