unit Windows;

interface

type
  DWORD = LongWord;
  LPWSTR = PWideChar;
  LPCWSTR = PWideChar;
  BOOL = LongBool;

function GetCurrentDirectoryW(nBufferLength: DWORD; lpBuffer: LPWSTR): DWORD;
function SetCurrentDirectoryW(lpPathName: LPCWSTR): BOOL;

implementation

uses
  SysUtils;

function GetCurrentDirectoryW(nBufferLength: DWORD; lpBuffer: LPWSTR): DWORD;
var
  s: UnicodeString;
begin
  GetDir(0, s);
  StrPLCopy(lpBuffer, s, nBufferLength);
  Exit(Length(lpBuffer));
end;

function SetCurrentDirectoryW(lpPathName: LPCWSTR): BOOL;
begin
  ChDir(lpPathName);
  Exit(True);
end;

end.
