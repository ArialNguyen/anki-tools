import requests
from dotenv import dotenv_values

# Lấy 1 key bất kỳ trong file .env của bạn
env_dict = dotenv_values(".env")
api_key = list(env_dict.values())[0]

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
response = requests.get(url)

if response.status_code == 200:
    models = response.json().get('models', [])
    print("🔥 DANH SÁCH MODEL HỢP LỆ TRÊN SERVER:")
    for m in models:
        # Lọc ra những model hỗ trợ tạo text (generateContent)
        if 'generateContent' in m.get('supportedGenerationMethods', []):
            # Cắt bỏ chữ "models/" ở đầu để lấy tên chuẩn
            name = m['name'].replace("models/", "")
            if "gemma" in name.lower():
                print(f"✅ {name}")
else:
    print("Lỗi:", response.text)