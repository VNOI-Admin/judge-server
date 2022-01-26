const input_file_name = 'PoSt.InP';
const output_file_name = 'PoSt.OuT';

var
    a, b: int64;
    sum: int64;
begin
    assign(input, input_file_name); reset(input);
    assign(output, output_file_name); rewrite(output);
    read(a, b);
    sum := a + b;
    write(sum);
end.
