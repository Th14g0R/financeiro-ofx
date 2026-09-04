Option Explicit

Dim shell, fso, baseDir, pythonwPath, serverPath, command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
baseDir = fso.GetParentFolderName(baseDir)

pythonwPath = baseDir & "\.venv\Scripts\pythonw.exe"
serverPath = baseDir & "\windows_manager.py"

shell.CurrentDirectory = baseDir

command = """" & pythonwPath & """ """ & serverPath & """ --start"

shell.Run command, 0, False
