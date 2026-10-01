import requests
payload = {
    'model': 'auto',
    'messages': [{'role': 'user', 'content': 'What are Apollo Micro Systems main business segments?'}]
}
res = requests.post('http://localhost:5000/v1/chat/completions', json=payload)
print(res.text.encode('ascii', 'ignore').decode('ascii'))
