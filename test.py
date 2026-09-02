
import requests
payload = {
    'model': 'auto',
    'messages': [{'role': 'user', 'content': 'What is the live price of RELIANCE?'}]
}
res = requests.post('http://localhost:5000/v1/chat/completions', json=payload)
print(res.text.encode('ascii', 'ignore').decode('ascii'))

