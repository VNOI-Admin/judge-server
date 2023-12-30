{$MODE OBJFPC}
{$R-,Q-,S-,I+}
{$OPTIMIZATION LEVEL2}
program Checker;
uses Windows, SysUtils, Math;

const
  prefix = 'POST';
  InputFile  = prefix + '.INP';
  OutputFile = prefix + '.OUT';
  AnswerFile = prefix + '.OUT';
var
  dirT, dirC: WideString;
  fi, fo, fa: TextFile;

procedure GenErr(const s: string; const param: array of const);
begin
  raise Exception.CreateFmt(s, param);
end;

procedure ReadDirs;
var
  s: AnsiString;
begin
  ReadLn(s); dirT := Utf8Decode(s);
  ReadLn(s); dirC := Utf8Decode(s);
end;

procedure OpenFiles;
var
  CurrentDir: array[0..Max_Path + 1] of WideChar;
begin
  GetCurrentDirectoryW(Max_Path, CurrentDir);
  SetCurrentDirectoryW(PWideChar(dirT));
  AssignFile(fi, InputFile); Reset(fi);
  AssignFile(fa, AnswerFile); Reset(fa);
  SetCurrentDirectoryW(CurrentDir);
  SetCurrentDirectoryW(PWideChar(dirC));
  AssignFile(fo, OutputFile); Reset(fo);
end;

procedure CloseFiles;
begin
  CloseFile(fi);
  CloseFile(fa);
  CloseFile(fo);
end;

procedure DoCheck;
var a, b, p: longint;
begin
  read(fi, a, b);
  read(fo, p);
  if a + b <> p then
    begin
      writeln('Incorrect');
      writeln('0.0');
    end
  else
    begin
        writeln('Correct');
        writeln('1.0');
    end;
end;

begin
  try
    try
      ReadDirs;
      OpenFiles;
      DoCheck;
    finally
      CloseFiles;
    end;
  except
    on E: Exception do
      begin
        WriteLn(E.Message);
        WriteLn('0.0');
      end;
  end;
end.
