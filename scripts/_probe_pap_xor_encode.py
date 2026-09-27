import re
import requests

text = requests.get(
    "https://pap.niointernet.com.br/administrativo/bundle.js", timeout=120
).text

# localizar modulo xor 529
for pat in [
    r"529:function\(module,exports",
    r"529:function\(",
    r"\/\* 529 \*\/",
    r"exports\.encode\s*=",
    r"\.encode=function",
    r"encode:function",
]:
    print("pat", pat, "->", bool(re.search(pat, text[:500000])))

# procurar encode/decode perto da key
idx = text.find('key="-5Hsrpt5')
# procurar definicao de xor.encode no require 529 - geralmente no mesmo chunk
# var xor=__webpack_require__(529)
# achar function encode( no arquivo com Base64

for m in re.finditer(r"encode:function\(([a-z]),([a-z])\)\{.{0,400}", text):
    snippet = m.group(0)
    if "charCodeAt" in snippet or "btoa" in snippet or "Base64" in snippet or "fromCharCode" in snippet:
        print("ENCODE CANDIDATE at", m.start())
        print(snippet[:450])
        print("---")

print("\n=== search xor library patterns ===")
for pat in ["exports.encode=function", "e.encode=function", "n.encode=function", "t.encode=function"]:
    start = 0
    c = 0
    while c < 5:
        j = text.find(pat, start)
        if j < 0:
            break
        sn = text[j : j + 350]
        if "charCodeAt" in sn:
            print(pat, j)
            print(sn)
            print("---")
            c += 1
        start = j + 1
