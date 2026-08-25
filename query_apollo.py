import requests; print(requests.post('http://127.0.0.1:5000/api/query', json={'question': 'What were the primary revenue drivers for Apollo Microsystems in FY25?', 'symbols': ['APOLLO']}).json())
