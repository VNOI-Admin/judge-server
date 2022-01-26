import sys
sys.stdin = open('wrongfilename.inp', 'r')
sys.stdout = open('wrongfilename.out', 'w')

print(sum([int(x) for x in input().split()]))
