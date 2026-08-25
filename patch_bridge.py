import re

with open('compilation_bridge.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('["openkb"', '[r"C:\\Users\\hp\\AppData\\Roaming\\Python\\Python310\\Scripts\\openkb.exe"')

with open('compilation_bridge.py', 'w', encoding='utf-8') as f:
    f.write(text)
