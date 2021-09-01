import time

command, data = input().split(' ')

# This makes the manager need to wait for 1 sec for
# each process.
time.sleep(1)

if command == "ENCODE":
    print("lets_pretend_this_is_a_ciphertext_" + data)
else:
    print(data[34:])
