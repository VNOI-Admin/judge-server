from sys import stdout
print(0)
stdout.flush()
N = int(input())
for i in range(1, N + 1):
    print(i)
    stdout.flush()
