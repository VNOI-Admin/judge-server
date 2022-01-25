import sys
sys.stdin = open('post.inp', 'r')
sys.stdout = open('post.out', 'w')

print(sum([int(x) for x in input().split()]))
