// Non-zero initializers force the whole array into .data, so the .s file is hundreds of MB.
struct S {
    long long a = -1, b = -2, c = -3, d = -4;
};
S arr[4000000];

int main() {}
