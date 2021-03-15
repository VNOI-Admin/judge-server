def compress(s):
    if not isinstance(s, str):
        s = s.decode('utf-8')
    if len(s) <= 64:
        return s
    return s[:30] + '...' + s[-31:]


def english_ending(x):
    x %= 100
    if x // 10 == 1:
        return 'th'
    if x % 10 == 1:
        return 'st'
    if x % 10 == 2:
        return 'nd'
    if x % 10 == 3:
        return 'rd'
    return 'th'
