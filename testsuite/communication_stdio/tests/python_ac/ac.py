import time

time.sleep(1)
command, data = input().split(' ')
if command == "ENCODE":
    print("lets_pretend_this_is_a_ciphertext_" + data)
else:
    print(data[34:])
