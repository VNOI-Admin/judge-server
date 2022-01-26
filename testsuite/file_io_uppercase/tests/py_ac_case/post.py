import sys
sys.stdin = open('PoSt.InP', 'r')
sys.stdout = open('PoSt.OuT', 'w')

print(sum([int(x) for x in input().split()]))
