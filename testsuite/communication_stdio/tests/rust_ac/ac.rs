use std::io::stdin;

fn main() {
    let mut line = String::new();
    stdin().read_line(&mut line).unwrap();
    let (command, data) = line.trim().split_once(' ').unwrap();
    if command == "ENCODE" {
        println!("lets_pretend_this_is_a_ciphertext_{}", data);
    } else {
        println!("{}", &data[34..]);
    }
}
