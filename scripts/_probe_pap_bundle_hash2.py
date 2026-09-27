import re
import requests

text = requests.get(
    "https://pap.niointernet.com.br/administrativo/bundle.js", timeout=120
).text

i = text.find('key="-5Hsrpt5')
print("=== XOR CONTEXT ===")
print(text[i - 800 : i + 1200])
print("\n\n=== module 529 xor snippets ===")
# webpack module 529
m = re.search(r"529:function\([^)]*\)\{", text)
if m:
    print(text[m.start() : m.start() + 1500])

print("\n\n=== _getAuthorizationToken ===")
for m in re.finditer(r"_getAuthorizationToken=function\([^)]*\)\{.{0,800}", text):
    print(m.group(0)[:800])
    print("---")
    break

print("\n\n=== encodeObjectBase64Xor usages ===")
start = 0
for _ in range(8):
    j = text.find("encodeObjectBase64Xor(", start)
    if j < 0:
        break
    print(text[j - 100 : j + 180].replace("\n", " "))
    print("---")
    start = j + 1

print("\n\n=== token concat patterns ===")
for pat in [
    "encodeObjectBase64Xor(JSON",
    "encodeObjectBase64Xor(JSON.stringify",
    "encodeObjectBase64Xor((new Date",
    "+encodeObjectBase64Xor",
    "concat(encodeObjectBase64Xor",
]:
    j = text.find(pat)
    print(pat, j)
    if j >= 0:
        print(text[j - 120 : j + 200].replace("\n", " ")[:350])
        print("---")
